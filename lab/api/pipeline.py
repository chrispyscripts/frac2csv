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

import fitz

import canyon
import frac_core as fc
import halliburton_ifs as ifs
import leucrotta as lc
import bj1
import bj_summary
import calfrac_summary
import liberty_summary
import lib1
import peloton_frac as pel
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
            # the chart's printed time-axis label set, where the template
            # reports one (BJ) — see _split_bj_windows
            "axis_window": getattr(meta, "axis_window", ""),
            "warnings": list(getattr(meta, "warnings", []))}


def _series(meta, samples, data, source, page=None, units=None, labels=None,
            geom=None, scales=None):
    return {"type": "series", "meta": meta, "samples": samples, "data": data,
            "units": units or {}, "labels": labels or {}, "source": source,
            "page": page, "geom": geom, "scales": scales or {}}


def _window_tags(windows):
    """{axis window: printed tag} — unique across the windows given, and
    every character of it printed on the page.

    The axis START normally separates two charts of one stage; where it does
    not, widen to start..end (the end's clock alone when both fall on the day
    the start names). Returns None if even that leaves them indistinguishable,
    so the caller can leave the stage alone rather than invent a name for it.
    """
    for widen in (False, True):
        tags = {}
        for w in windows:
            labs = w.split("|")
            tag = labs[0]
            if widen and len(labs) > 1:
                day, _sp, clock = labs[-1].partition(" ")
                tag += ".." + (clock if day == labs[0].split(" ")[0]
                               else labs[-1])
            tags[w] = tag
        if len(set(tags.values())) == len(windows):
            return tags
    return None


def _split_bj_windows(results, notes):
    """Separate BJ charts that share a stage number but not a time axis.

    BJ names an aborted or re-pumped run in the chart title ("Stage 06 Plug
    Slip", "Stage 10.1") and bj1 keeps that suffix in the stage key, which is
    what stops those from merging. A few stages are charted twice with NO
    printed difference whatsoever — a zoomed detail view beside the full
    treatment, or two genuinely separate treatments — so there is no suffix to
    read and both charts land under one key. Every consumer then merges
    same-stage charts by sample index (pipeline_export.build_well, the Lab's
    stageItems), taking the row count from the longest and the meta from the
    first: the short chart's channels win the columns and get padded out to
    the long chart's length, so the block's duration, sample count and time
    axis each describe a different chart.

    Every page of ONE chart — the main plot and the single-series auxiliary
    pages beside it — prints an identical "Mon-DD HH:MM" axis label set, and
    two charts of one stage never do. So a stage carrying more than one window
    is more than one chart. Name each for the window it prints; that is the
    only distinction the report offers, and it beats inventing a "run 2" the
    report never printed.
    """
    by_stage = {}
    for r in results:
        if r.get("source") == "BJ chart":
            by_stage.setdefault(r["meta"].get("stage") or "?", []).append(r)
    for stage, grp in by_stage.items():
        wins = []                       # page order, i.e. chronological
        for r in grp:
            w = r["meta"].get("axis_window") or ""
            if w and w not in wins:
                wins.append(w)
        if len(wins) < 2:
            continue
        tags = _window_tags(wins)
        if not tags:
            notes.append(f"Stage {stage}: {len(wins)} charts under one title "
                         f"whose printed time axes could not be told apart — "
                         f"left merged")
            continue
        for r in grp:
            w = r["meta"].get("axis_window") or ""
            if w in tags:
                r["meta"]["stage"] = f"{stage} {tags[w]}"
        notes.append(f"Stage {stage} is charted {len(wins)} times under one "
                     f"title — separated by printed time axis as "
                     + ", ".join(f'"{stage} {tags[w]}"' for w in wins))


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


def extract_document(doc, sample_sec=1.0, enable_raster=True, filename=None):
    """Run every template over `doc` (a fitz.Document). -> (results, notes).

    `filename` (when known) supplies a chunk-independent year hint for chart
    systems whose plots label only month-day (BJ-1)."""
    results, notes = [], []
    npages = len(doc)
    raster = enable_raster and raster_available()

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
        page = doc[pno]
        text = page.get_text()
        if lc.detect(page) or sk.detect(page):
            continue                                    # handled elsewhere

        if "(IFS v" in text:
            if re.search(r"Interval\s+\d+\s*[-–]\s*Entire Treatment", text) and \
               len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) >= 3:
                try:
                    meta, samples, data, chinfo = ifs.extract_page(page)
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
                                       scales=getattr(meta, "axes", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: Liberty chart failed — {e}")
            continue

        if bj1.detect(page):
            try:
                meta, samples, data, units = bj1.extract_page(page)
                results.append(_series(_md(meta), samples, data,
                                       "BJ chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: BJ chart failed — {e}")
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
                            f"STEP {kind} chart (raster)", pno + 1, units))
            except Exception as e:
                notes.append(f"p{pno + 1}: STEP chart failed — {e}")
            continue

        if fc.page_kind(page) == "vector":
            try:
                meta, samples, data = fc.extract_page(page, sample_sec=sample_sec)
                results.append(_series(_md(meta), samples, data,
                                       "MView chart", pno + 1,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "scales", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: vector chart failed — {e}")

    # CalFrac/MView 2013-vintage: a stage's channels are split across several
    # consecutive chart pages, only the FIRST of which carries the stage
    # number (rate+pressure numbered; the concentration pages left blank).
    # Fill the stage number down onto those blank pages so build_well merges
    # the four channels into one stage, and drop the empty whole-job overview
    # pages (no curves) that would otherwise become phantom stages.
    last_stage, keep = None, []
    for r in results:
        if r.get("source") != "MView chart":
            keep.append(r)
            continue
        if not r["data"]:                       # whole-job overview, no curves
            continue
        st = r["meta"].get("stage")
        if st:
            last_stage = st
        elif last_stage:
            r["meta"]["stage"] = last_stage     # blank conc page -> its stage
        keep.append(r)
    results[:] = keep

    # a BJ stage charted twice under one title -> one block per printed
    # time axis, instead of the two fusing into a block that matches neither
    _split_bj_windows(results, notes)

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
    return results, notes
