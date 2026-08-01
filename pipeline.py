"""Shared extraction dispatch for every supported frac-report template.

One entry point, `extract_document(doc, ...)`, runs the whole template
registry over a PDF and returns raw results (numpy time-series + engineering
tables). Both consumers build on this:

  - the desktop app (frac2csv_gui.py) writes CSVs/reports from the raw arrays
  - Carmine's Lab (lab/api/extract.py) serializes the same results to JSON

Vector templates run everywhere. Raster templates (Step-1, Hal-1) need the
tesseract OCR engine, so they only run when it is present and enabled — which
is the desktop app, not the serverless Lab.

Result shapes (list of dicts):
  {"type": "series", "meta": {...}, "samples": np, "data": {name: vals},
   "units": {name: unit}, "labels": {name: label}, "source": str, "page": int}
  {"type": "table", "title": str, "well": str, "uwi": str, "formation": str,
   "columns": [...], "rows": [[...]], "source": str}
"""
import re
from datetime import datetime, timedelta

import fitz

import canyon
import frac_core as fc
import halliburton_ifs as ifs
import leucrotta as lc
import bj1
import bj_summary
import calfrac_summary
import calfrac_progress as cprog
import liberty_summary
import lib1
import peloton_frac as pel
import step_vec
import pipeline_export as pe
import sk_fracr as sk
import trican2

try:
    import auto_raster as ar
    import step1
    import hal1
    _RASTER_OK = True
except Exception:                       # pragma: no cover - optional deps
    _RASTER_OK = False


def _md(meta):
    """PageMeta -> plain dict the consumers share."""
    return {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
            "date": meta.date, "start_time": meta.start_time,
            "duration_min": meta.duration_min,
            "warnings": list(getattr(meta, "warnings", []))}


def _series(meta, samples, data, source, page=None, units=None, labels=None,
            geom=None, scales=None, frames=None):
    # `scales` is each curve's PRINTED tick range — what the y-axis reads.
    # `frames` is that same axis read at the plot-frame edges (geom v0/v1),
    # which is where ghost mode stretches the page to. They differ by the
    # per-curve tick-fit error, so drawing against `scales` while the backdrop
    # is placed by the frame leaves the curve sitting a percent or two off the
    # ink. Ship both: labels come from `scales`, positions from `frames`.
    return {"type": "series", "meta": meta, "samples": samples, "data": data,
            "units": units or {}, "labels": labels or {}, "source": source,
            "page": page, "geom": geom, "scales": scales or {},
            "frames": frames or {}}


def _split_progress(page, meta, samples, data, ztimes, sample_sec, notes, pno,
                    _last_progress):
    """One CalFrac "Progress" page -> one (meta, samples, data, geom) per zone.

    The page plots several zones end to end and names none of them, so without
    this the whole plot lands in build_well's "?" block as a single fused
    stage. Cuts come from the pumping data; the zone numbers come from the
    page's "Zones N-M" caption and the clock times from the Multiple-Zone
    summary table that precedes it.
    """
    def whole(zr=None):
        md = _md(meta)
        if zr:
            # Name it for the zones it holds. Left as None it would inherit the
            # previous page's stage from the fill-down below and quietly append
            # a whole job's data to one real stage's block.
            md["stage"] = f"{zr[0]}-{zr[1]}"
            md["multi_zone"] = True
        return [(md, samples, data, getattr(meta, "geom", None))]

    zr = cprog.zone_range(page)
    if not zr:
        # The Bottom Hole page plots the same window as the Surface page it
        # sits directly behind, but prints no caption. Borrow that page's
        # zones — only from the page immediately before, and only when the
        # spans match. 00004 repeats 200-minute Progress pages throughout the
        # document, and a looser rule handed a caption to charts 20 pages away.
        prev = _last_progress[0]
        if prev and prev[2] == pno - 1 and \
                abs(len(samples) - prev[1]) <= max(4, 0.02 * prev[1]):
            zr = prev[0]
        else:
            return whole()
    else:
        _last_progress[0] = (zr, len(samples), pno)
    lo, hi = zr
    nz = hi - lo + 1
    span_min = len(samples) * sample_sec / 60.0
    # First choice is the pumping data: where the pumps stopped is not a matter
    # of opinion. Only when the zones ran continuously, leaving no break to
    # find, fall back to the times the summary table prints.
    zones = list(range(lo, hi + 1))
    bounds = cprog.split_page(samples, data, nz, sample_sec)
    by_table = False
    if bounds is None:
        fallback = cprog.table_split(ztimes, lo, hi, len(samples),
                                     sample_sec, span_min)
        if fallback is None:
            notes.append(f"p{pno + 1}: captioned 'Zones {lo}-{hi}' but neither "
                         f"the pumping data nor the summary times separate "
                         f"{nz} treatments, so the page is left whole rather "
                         f"than split onto the wrong zones")
            return whole(zr)
        bounds, zones = fallback
        by_table = True
        if len(zones) != nz:
            notes.append(f"p{pno + 1}: captioned 'Zones {lo}-{hi}' but the "
                         f"summary table times only cover zones "
                         f"{zones[0]}-{zones[-1]}; split on those")

    geom = getattr(meta, "geom", None)
    page_date = getattr(meta, "date", "") or cprog.job_date(page) or ""
    # Fit ONE clock origin for the page and read every zone off the chart's
    # axis from there. Stamping each zone with its own table entry and the rest
    # from the axis mixed two clocks in one well — stage 11 at 18:06 and stage
    # 12 at 03:36. When the table drove the split the origin is exact by
    # construction: the first zone's printed start.
    offsets = [a * sample_sec / 60.0 for a, _b in bounds]
    if by_table:
        anchor = (cprog.zone_start_minutes(ztimes, zones[0]), len(zones))
    else:
        anchor = cprog.anchor_t0(zones, offsets, ztimes)
        if anchor is None:
            # Nothing corroborated, but the chart still begins when its first
            # zone began. On a two-zone page there is no third time to break
            # the tie, and a page whose zones disagree by an hour is still
            # better placed on the clock than left at 00:00.
            first = cprog.zone_start_minutes(ztimes, zones[0])
            if first is not None:
                anchor = (first, 1)
                notes.append(f"p{pno + 1}: zones {lo}-{hi} — the printed start "
                             f"times disagree with the chart's spacing, so it "
                             f"is placed on the clock by zone {zones[0]}'s "
                             f"start alone")
            elif ztimes:
                notes.append(f"p{pno + 1}: zones {lo}-{hi} — no usable start "
                             f"time in the summary table, so the zones are "
                             f"split but timed from the chart's own axis")
    out = []
    for j, (a, b) in enumerate(bounds):
        zone = zones[j] if j < len(zones) else zones[-1] + (j - len(zones) + 1)
        label = str(zone)
        md = _md(meta)
        md["stage"] = label
        md["date"] = page_date
        # how many zones the page this came from was covering — a zone read off
        # a 12-zone overview is coarser than the same zone on its own chart
        md["zone_span"] = nz
        md["duration_min"] = (b - a) * sample_sec / 60.0
        # seconds from midnight of page_date: the fitted origin (0 when the
        # table gave nothing usable) plus this zone's place on the axis
        secs = int(round((anchor[0] * 60 if anchor else 0) + a * sample_sec))
        md["start_time"] = (f"{secs // 3600 % 24:02d}:"
                            f"{secs % 3600 // 60:02d}:{secs % 60:02d}")
        if secs >= 24 * 3600 and page_date:
            md["date"] = (datetime.strptime(page_date, "%Y-%m-%d")
                          + timedelta(days=secs // (24 * 3600))
                          ).strftime("%Y-%m-%d")
        if not anchor:
            md["warnings"] = md["warnings"] + [
                f"zone {label}: no usable start time in the zone summary "
                f"table — timed from the chart's own axis instead"]
        # geom maps a page coordinate to seconds from the PAGE's start; this
        # segment's clock restarts at its own first sample, so slide the origin
        pgeom = geom
        if geom and a:
            pgeom = dict(geom)
            pgeom["ta"] = geom.get("ta", 0.0) - a * sample_sec
        out.append((md, samples[a:b] - samples[a],
                    {k: v[a:b] for k, v in data.items()}, pgeom))
    return out


def raster_available():
    return _RASTER_OK and ar.available()


def _bj_totals(doc):
    """doc-level wrapper: the BJ per-interval Totals table as {columns, rows}."""
    for p in range(doc.page_count):
        if bj_summary.is_totals_page(doc[p]):
            tab = bj_summary.parse_totals(doc[p])
            if tab:
                return tab
    return None


# ---------- table normalisation ----------
# Tables come from several parsers, each carrying the source report's own
# formatting. The seconds export has one house style, and a table sitting
# beside it in the same folder should read the same way.

_DATE_COL = re.compile(r"(?:^|_)(start|end|date|time|datetime)(?:$|_)", re.I)
_DT_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M",
               "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
               "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d")


def canon_uwi(raw):
    """'202/D-069-A/094-G-07/00' -> '202D069A094G0700', matching the UWI the
    seconds export writes. Separators vary by report; the canonical form does
    not."""
    return re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()


def _fmt_dt(v):
    """Report date/time -> 'YYYY-mm-dd HH:MM:SS', the seconds DATETIME format.
    Anything unparseable is returned untouched: these cells sometimes hold
    spillover text from the table above rather than a date."""
    s = str(v or "").strip()
    if not s:
        return v
    for f in _DT_FORMATS:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return v


def _normalise_tables(results, filename=None):
    fallback = pe.filename_uwi(filename) if filename else ""
    for r in results:
        if r.get("type") != "table":
            continue
        cols = list(r.get("columns") or [])
        rows = [list(x) for x in (r.get("rows") or [])]
        for i, c in enumerate(cols):
            if not _DATE_COL.search(str(c)):
                continue
            for row in rows:
                if i < len(row):
                    row[i] = _fmt_dt(row[i])
        if not any(str(c).strip().lower() == "uwi" for c in cols):
            uwi = canon_uwi(r.get("uwi")) or fallback
            cols = ["UWI"] + cols
            rows = [[uwi] + row for row in rows]
        r["columns"], r["rows"] = cols, rows


def extract_document(doc, sample_sec=1.0, enable_raster=True, filename=None,
                     on_page=None):
    """Run every template over `doc` (a fitz.Document). -> (results, notes).

    `filename` (when known) supplies a chunk-independent year hint for chart
    systems whose plots label only month-day (BJ-1).

    `on_page(done, total)` is called as each page is finished, so a caller can
    report progress on a long report instead of blocking silently."""
    results, notes = [], []
    npages = len(doc)
    raster = enable_raster and raster_available()

    # CalFrac multi-zone "Progress" charts need the zone-time tables, but most
    # documents have none — read them the first time a Progress page turns up
    _zone_times = [None]
    # the last captioned Progress page, so its uncaptioned twin can borrow it
    _last_progress = [None]
    # schematic/table pages that draw like charts — reported as one line, not
    # one per page: a 171-page report has dozens and they are not errors
    _not_charts = []

    # year hint from the COMP filename survives client-side page chunking
    yhint = bj1.filename_year(filename)
    if yhint:
        try:
            doc._bj1_year_hint = yhint
        except Exception:
            pass

    # --- Leucrotta acquisition charts (whole-document, stitched by stage) ---
    if any(lc.detect(doc[p]) for p in range(npages)):
        try:
            groups = lc.extract_document(doc)
        except Exception as e:
            groups = []
            notes.append(f"Leucrotta charts failed — {e}")
        for g in groups:
            t0 = g["t0_seconds"]
            start = (f"{int(t0 // 3600) % 24:02d}:"
                     f"{int(t0 % 3600 // 60):02d}:{int(t0 % 60):02d}")
            meta = {"title": f"Stage {g['stage']}", "uwi": g["well"],
                    "stage": str(g["stage"]), "date": g["date"],
                    "start_time": start,
                    "duration_min": len(g["samples"]) / 60.0, "warnings": []}
            results.append(_series(meta, g["samples"], g["data"],
                                   "acquisition chart (Leucrotta-style)",
                                   page=(g.get("pages") or [None])[0],
                                   units=g["units"]))
        if groups:
            notes.append(f"{len(groups)} stage(s) from acquisition chart pages.")

    # --- per-page chart templates ---
    for pno in range(npages):
        if on_page is not None:
            try:
                on_page(pno, npages)
            except Exception:
                pass                      # progress must never break a run
        page = doc[pno]
        text = page.get_text()
        if lc.detect(page) or sk.detect(page):
            continue                                    # handled elsewhere

        if "(IFS v" in text:
            # "Entire Treatment" is the v4.3.1 wording; v4.6.3 titles the same
            # page "Interval 1 – Main Treatment". Requiring the older phrase
            # dropped every chart in the newer reports — 24 of 36 IFS files
            # came back "no extractable data" with no note explaining it,
            # because the skip below is silent. Carmine's alias table already
            # lists both under Hal-2's chart_headers_include.
            # The clock-label count stays: it is what rejects the table of
            # contents, which also names intervals and carries the IFS footer.
            titled = re.search(
                r"Interval\s+\d+\s*[-–]\s*(?:Entire|Main)\s+Treatment", text)
            # v4.2.0 names no interval at all — the section number carries it
            sect = None if titled else ifs.section_stage(page)
            if (titled or sect) and \
               len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) >= 3:
                try:
                    meta, samples, data, chinfo = ifs.extract_page(page)
                    if sect and not getattr(meta, "stage", None):
                        meta.stage = str(sect[0])
                    units = {k: v["unit"] for k, v in chinfo.items()}
                    labels = {k: v["label"] for k, v in chinfo.items()}
                    results.append(_series(_md(meta), samples, data,
                                           "Halliburton IFS chart", pno + 1,
                                           units, labels))
                except Exception as e:
                    notes.append(f"p{pno + 1}: IFS chart failed — {e}")
            continue

        if lib1.detect(page):
            try:
                meta, samples, data, units = lib1.extract_page(page)
                results.append(_series(_md(meta), samples, data,
                                       "Liberty chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None),
                                       frames=getattr(meta, "axes_frame", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: Liberty chart failed — {e}")
            continue

        if bj1.detect(page):
            try:
                meta, samples, data, units = bj1.extract_page(page)
                results.append(_series(_md(meta), samples, data,
                                       "BJ chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None),
                                       frames=getattr(meta, "axes_frame", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: BJ chart failed — {e}")
            continue

        if step_vec.detect(page):
            # STEP filed as vector: no OCR needed, and step1 only matches the
            # scanned twin, so without this the whole file reports no data.
            try:
                meta, samples, data, units = step_vec.extract_page(page, sample_sec)
                results.append(_series(_md(meta), samples, data,
                                       "STEP chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None),
                                       frames=getattr(meta, "axes_frame", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: STEP vector chart failed — {e}")
            continue

        if canyon.detect(page):
            try:
                meta, samples, data, units = canyon.extract_page(page)
                results.append(_series(_md(meta), samples, data,
                                       "Canyon chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: Canyon chart failed — {e}")
            continue

        if raster and hal1.detect(page):
            try:
                md, samples, chans, info = hal1.extract_page(page)
                data = {c["label"]: c["values"] for c in chans}
                units = {c["label"]: c["unit"] for c in chans}
                meta = {"title": f"Treatment interval {md.get('stage') or '?'}",
                        "uwi": md.get("uwi", ""), "stage": str(md.get("stage") or ""),
                        "date": "", "start_time": "00:00:00",
                        "duration_min": len(samples) / 60.0, "warnings": []}
                if data:
                    results.append(_series(meta, samples, data,
                                           "Halliburton treatment plot (raster)",
                                           pno + 1, units))
            except Exception as e:
                notes.append(f"p{pno + 1}: Halliburton plot failed — {e}")
            continue

        if raster and step1.detect(page):
            try:
                md, charts = step1.extract_page(page, sample_sec)
                if md.get("kind") == "main":
                    for tag, samples, chans, info in charts:
                        data = {c["label"]: c["values"] for c in chans}
                        units = {c["label"]: c["unit"] for c in chans}
                        frames = {c["label"]: c["axis_frame"] for c in chans
                                  if c.get("axis_frame")}
                        if not data:
                            continue
                        kind = "surface" if tag == "t" else "chemical"
                        meta = {"title": f"Interval {md.get('stage') or '?'} "
                                f"({kind})", "uwi": "",
                                "stage": str(md.get("stage") or ""),
                                "date": "", "start_time": "00:00:00",
                                "duration_min": len(samples) / 60.0,
                                "warnings": []}
                        results.append(_series(
                            meta, samples, data,
                            f"STEP {kind} chart (raster)", pno + 1, units,
                            geom=info.get("geom"), frames=frames))
            except Exception as e:
                notes.append(f"p{pno + 1}: STEP chart failed — {e}")
            continue

        if fc.page_kind(page) == "vector":
            if not cprog.is_chart_page(page):
                _not_charts.append(pno + 1)     # summarised after the loop
                continue
            if fc.is_chemicals(page):
                notes.append(f"p{pno + 1}: chemicals chart — additive "
                             f"concentrations, not treatment channels")
                continue
            try:
                meta, samples, data = fc.extract_page(page, sample_sec=sample_sec)
            except Exception as e:
                notes.append(f"p{pno + 1}: vector chart failed — {e}")
                continue
            geom = getattr(meta, "geom", None)
            scales = getattr(meta, "scales", None)
            if data and cprog.detect(page):
                # a "Progress" page: several zones on one plot, no stage named
                if _zone_times[0] is None:
                    _zone_times[0] = cprog.times_for_document(doc)
                for part in _split_progress(page, meta, samples, data,
                                            cprog.times_before(_zone_times[0], pno),
                                            sample_sec, notes, pno, _last_progress):
                    pmeta, psamples, pdata, pgeom = part
                    results.append(_series(pmeta, psamples, pdata,
                                           "MView chart", pno + 1,
                                           geom=pgeom, scales=scales))
                continue
            results.append(_series(_md(meta), samples, data,
                                   "MView chart", pno + 1,
                                   geom=geom, scales=scales))

    # CalFrac/MView 2013-vintage: a stage's channels are split across several
    # consecutive chart pages, only the FIRST of which carries the stage
    # number (rate+pressure numbered; the concentration pages left blank).
    # Fill the stage number down onto those blank pages so build_well merges
    # the four channels into one stage, and drop the empty whole-job overview
    # pages (no curves) that would otherwise become phantom stages.
    if _not_charts:
        notes.append(f"{len(_not_charts)} page(s) skipped as schematics or "
                     f"tables that draw like charts (p"
                     f"{', p'.join(str(x) for x in _not_charts[:8])}"
                     f"{', …' if len(_not_charts) > 8 else ''})")

    last_stage, keep = None, []
    for r in results:
        if r.get("source") != "MView chart":
            keep.append(r)
            continue
        if not r["data"]:                       # whole-job overview, no curves
            continue
        if r["meta"].get("multi_zone"):
            # a job-length Progress chart already named for its zone range —
            # it is not a stage, so it neither takes nor sets the running one
            keep.append(r)
            continue
        st = r["meta"].get("stage")
        if st:
            last_stage = st
        elif last_stage:
            r["meta"]["stage"] = last_stage     # blank conc page -> its stage
        keep.append(r)
    results[:] = keep

    # A well can chart the same zone twice: once on a job-length overview
    # ("Zone 1-12") and again on a chart of its own ("Zones 12-14"). Both split
    # to a zone 12, and build_well would merge them into one block on a
    # first-writer-wins basis — silently picking whichever page came first in
    # the file. Prefer the narrower page: fewer zones on a plot means more
    # resolution per zone, and the wider one contributes nothing extra.
    best = {}
    for r in results:
        span = r.get("meta", {}).get("zone_span")
        if span is None:
            continue
        st = r["meta"].get("stage")
        best[st] = min(span, best.get(st, span))
    if best:
        results[:] = [r for r in results
                      if r.get("meta", {}).get("zone_span") is None
                      or r["meta"]["zone_span"] == best[r["meta"]["stage"]]]

    # --- SK 'FracR' per-stage engineering tables (document-level) ---
    if any(sk.detect(doc[p]) for p in range(npages)):
        header, rows = {}, []
        for pno in range(npages):
            page = doc[pno]
            if not sk.detect(page):
                continue
            if not header:
                for line in page.get_text().splitlines():
                    m = re.search(r"(.+?)\s+(19[12]/[\d-]+W\d)\s*(\w*)", line)
                    if m:
                        header = {"well": m.group(1).strip(), "uwi": m.group(2),
                                  "formation": m.group(3)}
                        break
            row = sk.parse_page(page)
            if row.get("stage") is not None:
                rows.append(row)
        if rows:
            cols = ["stage", "depth_m", "start", "end", "fluid_rate_m3min",
                    "downhole_rate_m3min"] + [c for c, *_ in sk.FIELDS]
            used = [c for c in cols if any(c in r for r in rows)]
            results.append({
                "type": "table",
                "title": f"{header.get('well', 'well')} — per-stage engineering data",
                "well": header.get("well", ""), "uwi": header.get("uwi", ""),
                "formation": header.get("formation", ""), "columns": used,
                "rows": [[r.get(c, "") for c in used] for r in rows],
                "source": "SK FracR report"})
            notes.append(f"{len(rows)} stage row(s) parsed from FracR tables.")

    # --- Peloton WellView (Regulatory Frac Stage Details / Frac Detail) ---
    try:
        ph, preg = pel.parse_document(doc)
    except Exception:
        ph, preg = {}, []
    try:
        pfd = pel.parse_frac_detail(doc)
    except Exception:
        pfd = []
    prows = preg if len(preg) >= len(pfd) else pfd
    if len(prows) >= 2:
        cols = sorted({k for r in prows for k in r if k != "page"},
                      key=lambda c: (c != "stage", c))
        results.append({
            "type": "table",
            "title": (ph.get("well") or "well") + " — per-stage engineering data (WellView)",
            "well": ph.get("well", ""), "uwi": ph.get("bh_uwi", ""),
            "formation": "", "columns": cols,
            "rows": [[r.get(c, "") for c in cols]
                     for r in sorted(prows, key=lambda r: r.get("stage", 0))],
            "source": "Peloton WellView report"})
        notes.append(f"{len(prows)} stage row(s) parsed from WellView tables.")

    # --- Trican 'STAGE INFORMATION' reports ---
    try:
        th, trows = trican2.parse_document(doc)
    except Exception:
        th, trows = {}, []
    if len(trows) >= 2:
        cols = [c for c in trican2.COLUMNS if any(c in r for r in trows)]
        results.append({
            "type": "table",
            "title": (th.get("well") or "well") + " — per-stage engineering data (Trican)",
            "well": th.get("well", ""), "uwi": th.get("uwi", ""),
            "formation": "", "columns": cols,
            "rows": [[r.get(c, "") for c in cols] for r in trows],
            "source": "Trican stage report (stages numbered by document order)"})
        notes.append(f"{len(trows)} stage row(s) parsed from Trican stage reports.")

    # --- "Summary Data": each chart provider's summary table pages (for
    # viewing) + the key per-stage summary table parsed into a grid. Keyed
    # to the chart provider actually present so summaries don't fire on the
    # wrong document. ---
    chart_srcs = {r["source"] for r in results if r["type"] == "series"}

    def _summary(mod, present, title, parse_fn):
        if not present:
            return
        try:
            groups = mod.find_summary_pages(doc)
        except Exception:
            groups = []
        if groups:
            results.append({"type": "summary", "groups": groups,
                            "source": title})
        try:
            tab = parse_fn(doc)
        except Exception as e:
            notes.append(f"{title} parse failed — {e}")
            return
        if tab and tab.get("rows"):
            results.append({
                "type": "table", "title": title,
                "well": "", "uwi": "", "formation": "",
                "columns": tab["columns"], "rows": tab["rows"],
                "source": title})

    _summary(bj_summary, "BJ chart" in chart_srcs,
             "Totals — per-interval frac summary",
             lambda d: _bj_totals(d))
    _summary(liberty_summary, "Liberty chart" in chart_srcs,
             "Stimulation Summary", liberty_summary.parse_stimulation)
    _summary(calfrac_summary, "MView chart" in chart_srcs,
             "Treatment Summary", calfrac_summary.parse_treatment_summary)

    if not results:
        extra = "" if raster else \
            " (raster/scanned templates need the tesseract OCR engine)"
        notes.append(f"No extractable charts or tables found in {npages} pages{extra}.")
    _normalise_tables(results, filename)
    return results, notes
