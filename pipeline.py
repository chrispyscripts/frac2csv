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
import bj_fracturing
import bj_summary
import calfrac_summary
import calfrac_progress as cprog
import calfrac_scan as cscan
import liberty_summary
import ocr_labels
import lib1
import peloton_frac as pel
import sanjel
import step_vec
import aliases
import pipeline_export as pe
import sk_fracr as sk
import daily_ops
import interval_sheet
import slb
import slb_tables
import trican2
import trican_b

try:
    import auto_raster as ar
    import step1
    import hal1
    import trican_charts as tcharts
    _RASTER_OK = True
except Exception:                       # pragma: no cover - optional deps
    _RASTER_OK = False

try:
    # read for the date a Canyon chart cannot print (see _canyon_dates), and
    # for its own tables
    import canyon_tables
except Exception:                       # pragma: no cover - not yet deployed
    canyon_tables = None

# Table parsers, each built and verified against the corpus before being
# wired in here. Optional so a deployment missing one still runs.
try:
    import step_summary
except Exception:                       # pragma: no cover
    step_summary = None
try:
    import hal1_tables
except Exception:                       # pragma: no cover
    hal1_tables = None
try:
    import ifs_tables
except Exception:                       # pragma: no cover
    ifs_tables = None
try:
    import sanjel_tables
except Exception:                       # pragma: no cover
    sanjel_tables = None
try:
    import calfrac_legacy
except Exception:                       # pragma: no cover
    calfrac_legacy = None


# The build stamp every IFS page carries, matched WITHOUT case. Builds to
# v4.6.3 print "(IFS v4.6.3)" and v6 prints "(IFS V6.0.0)"; a literal
# lowercase test read the entire v6 family as some other document. Nothing
# else about v6 needed changing — same gate, same reader, same numbers.
_IFS_MARK = re.compile(r"\(IFS\s*v", re.I)


def _md(meta):
    """PageMeta -> plain dict the consumers share."""
    return {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
            "date": meta.date, "start_time": meta.start_time,
            "duration_min": meta.duration_min,
            # the chart's printed time-axis label set, where the template
            # reports one (BJ) — see _split_bj_windows
            "axis_window": getattr(meta, "axis_window", ""),
            # a UWI the page prints that we deliberately do NOT trust as the
            # filing's own (Sanjel's banner names another well) — carried for
            # reference, the way sanjel_tables carries it on the table side
            "banner_uwi": getattr(meta, "banner_uwi", ""),
            # channels whose values a correction changed, named rather than
            # described, so the file-level notice can be built without
            # parsing the human sentence in `warnings`
            "warnings": list(getattr(meta, "warnings", []))}


def _variant_of(line):
    return (" BH" if re.search(r"\bbottom\s*hole\b", line, re.I)
            else " Surface" if re.search(r"\bsurface\b", line, re.I)
            else "")


def _mview_variant(page):
    """-> " Surface" / " BH" / "" from an MView page's own title line.

    Read through ocr_labels, so a Type3 filing gets the tag too. Without it
    the Surface and Bottom Hole pages of a zone share one key and merge, and
    both carry Treating Pressure — which is the collision this tag exists to
    prevent (#341).

    The title is not always the FIRST line, and reading only the first line
    was the same fault calfrac_progress.is_chart_page had: a portrait MView
    sheet rotates the plot and OCR reads the y-axis tick ladder before the
    caption, so page 73 of 00340 leads with "1400". Both sheets of every zone
    in the eight rotated filings came back untagged, which put them under one
    bare stage key with no way to tell them apart — precisely the collision
    above, in the files that had just been recovered.

    A later line has to look like a TITLE — see cprog.is_title_line — for the
    same reason is_chart_page requires it: the bare word "Chemicals" is also a
    column heading on the Treatment Summary grid.
    """
    try:
        lines = [l.strip() for l in ocr_labels.page_text(page).splitlines()
                 if l.strip()]
    except Exception:
        return ""
    tag = _variant_of(lines[0] if lines else "")
    if tag:
        return tag
    for line in lines[1:]:
        if cprog.is_title_line(line):
            tag = _variant_of(line)
            if tag:
                return tag
    return ""


# Placed on the corpus, not on one file. Over all 10,068 IFS pages in the 56
# __HAL filings, the largest image on a page that CHARTS FINE is 102,750px and
# the largest on a table of contents is 27,000, while the smallest image on a
# page whose chart is a bitmap is 245,403 — a 2.4x gap with nothing in it. The
# midpoint is the honest place to stand: ~1.55x clear of both sides, where the
# 200k this started at sat only 1.23x below the smallest real chart. The two
# values classify the measured corpus IDENTICALLY, because the gap is empty;
# the midpoint is for the files nobody has looked at yet.
_BIG_IMAGE_PX = 160_000


def _has_big_image(page):
    """Does this page carry an image big enough to BE the chart?"""
    try:
        return any(im[2] * im[3] > _BIG_IMAGE_PX
                   for im in page.get_images(full=True))
    except Exception:
        return False


_DAILY = re.compile(r"\bdaily\b|\bday\s*#|\breport\s*date\b|"
                    r"\bcompletions?\s+report\b|\bmorning\s+report\b", re.I)


def _is_daily(title):
    return bool(_DAILY.search(title or ""))


def _scanned_kind(doc, npages):
    """The title printed across the top of a scanned page, by OCR -> '' when
    nothing readable is there.

    A file whose every page is an image tells us nothing through the text
    layer, and the reader's only honest answer used to be two guesses at
    once. Tesseract ships inside the build, so read the banner and say.

    A few pages, not one: a filing can open on a cover sheet or a blank.
    """
    if not ocr_labels.available():
        return ""
    seen = []
    for i in _spread(npages, 4):
        try:
            txt = ocr_labels.page_text(doc[i]) or ""
        except Exception:
            continue
        # the banner is the first line with real words in it
        for line in txt.splitlines():
            line = " ".join(line.split())
            if len(line) >= 12 and sum(c.isalpha() for c in line) >= 8:
                seen.append(line[:90])
                break
    if not seen:
        return ""
    # A filing opens on a cover sheet, so the first page's banner names the
    # binder and an inside page names what the pages actually ARE: 00426's
    # cover says "COMPLETION / WORKOVER" and its body says "Daily Initial
    # Completions Report". The body is the useful answer.
    for line in seen:
        if _is_daily(line):
            return line
    return seen[-1] if len(seen) > 1 else seen[0]


def _spread(n, k):
    """k page indexes spread through a document, first one included."""
    if n <= k:
        return list(range(n))
    return [round(i * (n - 1) / (k - 1)) for i in range(k)]


def _why_nothing(doc, npages, raster):
    """Say WHY a file produced nothing, not just that it did.

    "No extractable charts or tables found" is true of a scanned daily report
    and true of a broken parser, and the client cannot tell them apart — which
    is most of what the "No extractable data" backlog is made of.

    The question is asked of the pages that DRAW CURVES, not of the document.
    A 359-page filing can carry its vendor name on 54 cover sheets and not one
    readable character on any of its 167 chart pages, and it is the chart pages
    that decide whether anything can be read. Sampled: this only runs when the
    document is already a dead end, but it should not cost minutes to say so.
    """
    def readable(page):
        t = page.get_text("text") or ""
        good = sum(1 for ch in t if ch.isprintable() and not ch.isspace())
        bad = sum(1 for ch in t if ord(ch) < 32 and ch not in "\n\r\t")
        # Type3 fonts with no ToUnicode hand back raw glyph codes: the page
        # LOOKS fine and extracts as control characters (00035, 00051 —
        # 200 of 344 characters). That is not a text layer anyone can use.
        return good > 20 and good > bad

    step = max(1, npages // 60)
    curve_pages = curve_readable = any_readable = looked = 0
    for i in range(0, npages, step):
        looked += 1
        try:
            page = doc[i]
        except Exception:
            continue
        ok = readable(page)
        any_readable += bool(ok)
        sat = 0
        try:
            for d in page.get_drawings():
                for key in ("color", "fill"):
                    c = d.get(key)
                    if c and max(c[:3]) - min(c[:3]) > 0.35:
                        sat += len(d["items"]) or 1
                if sat > 500:
                    break
        except Exception:
            pass
        if sat > 500:
            curve_pages += 1
            curve_readable += bool(ok)

    base = f"No extractable charts or tables found in {npages} pages"
    if not looked:
        return base + "."
    if not curve_pages and not any_readable:
        # Every page is a picture, so ASK one what it says instead of offering
        # the user two guesses. 00426/00428/00429 (#678) are 124-page runs of
        # Petrosight "Daily Initial Completions Report" sheets — daily ops
        # paperwork with no treatment chart anywhere in them. Told "it may be
        # a daily report", there is nothing for Carmine to do but flag it
        # again; told what it IS, he can stop.
        kind = _scanned_kind(doc, npages)
        if kind and _is_daily(kind):
            return (base + f" — every page is a picture, and read by OCR its "
                    f"pages are headed \"{kind}\". This is a daily operations "
                    f"report, not a treatment chart, so there is nothing here "
                    f"to extract. If this well should have charts, they are in "
                    f"another file.")
        if kind:
            return (base + f" — every page is a picture. Read by OCR its pages "
                    f"are headed \"{kind}\", and none of them draws a plotted "
                    f"curve. If this well should have charts, they are in "
                    f"another file.")
        return (base + " — this file draws no curves and carries no text layer "
                "at all: every page is a picture, so reading anything from it "
                "needs OCR. Its first page could not be read even that way.")
    if not curve_pages:
        return (base + " — no page in it draws a plotted curve, so there are "
                "no treatment charts here to miss. If this well should have "
                "charts, they are in another file.")
    if not curve_readable:
        where = ("none of them carry a text layer"
                 if not any_readable else
                 "none of them carry READABLE text — the rest of the file does, "
                 "so this is the charts' own font, not a scan")
        return (base + f" — {curve_pages} of the pages sampled draw plotted "
                f"curves and {where}. Nothing names the axes or the stages, so "
                f"reading them needs OCR of the labels.")
    if not raster:
        return base + " (raster/scanned templates need the tesseract OCR engine)."
    return base + "."


# Chars on a chart page below which it is drawing its labels rather than
# writing them. Carmine's number, and the measurement backs it: on 00121, a
# known vector-no-text filing, every one of 21 sampled chart pages carries
# EXACTLY ZERO readable characters, while a normal vector filing carries 323
# to 1077 on the same kind of page (00011 median 323, 00494 median 376). The
# gap is absolute, so 100 is not a tuned threshold — it is the middle of a
# chasm.
VECTOR_TEXT_MAX = 100


def vector_no_text(doc, sample=60):
    """Is this a filing whose CHARTS draw their labels as outlines?

    -> {"verdict": bool, "chart_pages": int, "with_text": int, "median": int}

    The question has to be asked of the pages that draw curves, not of the
    document, and that is the whole trick. 00121 carries 288,439 characters
    across 577 pages and 129 of those pages have text on them — by any
    document-wide count it is a text PDF. But the text is all cover sheets and
    tables, and not one character of it is on a chart: the labels there are
    converted to outlines, so no text-based detector can ever fire on them.

    Cheap by construction — sampled, and the drawing scan stops as soon as a
    page is known to be curvey — so it can be asked of a file before anything
    expensive is attempted on it.
    """
    npages = len(doc)
    if not npages:
        return {"verdict": False, "chart_pages": 0, "with_text": 0, "median": 0}
    step = max(1, npages // max(1, sample))
    counts = []
    for i in range(0, npages, step):
        try:
            page = doc[i]
        except Exception:
            continue
        sat = 0
        try:
            for d in page.get_drawings():
                for key in ("color", "fill"):
                    c = d.get(key)
                    if c and max(c[:3]) - min(c[:3]) > 0.35:
                        sat += len(d["items"]) or 1
                if sat > 500:
                    break
        except Exception:
            pass
        if sat <= 500:
            continue
        t = page.get_text("text") or ""
        counts.append(sum(1 for ch in t if ch.isprintable() and not ch.isspace()))
    if not counts:
        return {"verdict": False, "chart_pages": 0, "with_text": 0, "median": 0}
    counts.sort()
    med = counts[len(counts) // 2]
    return {"verdict": med < VECTOR_TEXT_MAX,
            "chart_pages": len(counts),
            "with_text": sum(1 for c in counts if c >= VECTOR_TEXT_MAX),
            "median": int(med)}


def _series(meta, samples, data, source, page=None, units=None, labels=None,
            geom=None, scales=None, frames=None, deduced=None):
    # `scales` is each curve's PRINTED tick range — what the y-axis reads.
    # `frames` is that same axis read at the plot-frame edges (geom v0/v1),
    # which is where ghost mode stretches the page to. They differ by the
    # per-curve tick-fit error, so drawing against `scales` while the backdrop
    # is placed by the frame leaves the curve sitting a percent or two off the
    # ink. Ship both: labels come from `scales`, positions from `frames`.
    #
    # `deduced` is {label: per-sample bool}, on the same grid as `data`: true
    # where the reader recovered the sample from under a curve painted over
    # it rather than from the channel's own ink. A chart that draws those
    # stretches like any other is claiming to have read something the page
    # never showed, which is the whole of the client's "conc having issues".
    return {"type": "series", "meta": meta, "samples": samples, "data": data,
            "units": units or {}, "labels": labels or {}, "source": source,
            "page": page, "geom": geom, "scales": scales or {},
            "frames": frames or {}, "deduced": deduced or {}}


def _split_progress(page, meta, samples, data, ztimes, sample_sec, notes, pno,
                    _last_progress, zclocks=None, all_times=None,
                    sheet_dates=None):
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
    borrowed = None
    if not zr:
        # The Bottom Hole page plots the same window as the Surface page it
        # sits directly behind, but prints no caption. Borrow that page's
        # zones — only from the page immediately before, and only when the
        # spans match. 00004 repeats 200-minute Progress pages throughout the
        # document, and a looser rule handed a caption to charts 20 pages away.
        prev = _last_progress[0]
        if prev and prev["page"] == pno - 1 and \
                abs(len(samples) - prev["n"]) <= max(4, 0.02 * prev["n"]):
            zr = prev["range"]
            borrowed = prev
        else:
            return whole()
    else:
        _last_progress[0] = {"range": zr, "n": len(samples), "page": pno,
                             "cuts": None, "zones": None, "anchor": None}
    lo, hi = zr
    nz = hi - lo + 1
    span_min = len(samples) * sample_sec / 60.0
    zones = list(range(lo, hi + 1))
    # Reuse the twin's cuts only if it HAS cuts. Requiring them — leaving this
    # page whole when the captioned one could not be split — cost 00070 19 of
    # its 24 stages: its captioned page finds no gaps and is left whole, while
    # this page splits cleanly on its own data. Falling through preserves that.
    if borrowed is not None and borrowed["cuts"] and len(samples):
        # Splitting this page independently cut it in slightly different places
        # than its Surface twin — measured across 17 two-page stages, mean
        # 27.1 s of skew and 40 s at worst. build_well then takes t0 from the
        # first page and unions the channels, so a stage's BH Prop Conc was
        # written against the Surface page's clock, half a minute out. The two
        # pages draw the same window, so reusing the twin's cuts as fractions
        # of its own length removes the skew by construction.
        n = len(samples)
        bounds = [(int(round(a * n)), int(round(b * n)))
                  for a, b in borrowed["cuts"]]
        zones = borrowed["zones"]
        anchor = borrowed["anchor"]
    else:
        # First choice is the pumping data: where the pumps stopped is not a
        # matter of opinion. Only when the zones ran continuously, leaving no
        # break to find, fall back to the times the summary table prints.
        bounds = cprog.split_page(samples, data, nz, sample_sec)
        by_table = False
        chosen_t0 = None
        if bounds is None:
            # The data may still show every boundary and a few dips besides —
            # concentration falls to zero during pad and flush, not only
            # between zones — and split_page only believes an exact count.
            # Let the printed start times say which of the candidates are
            # zone boundaries before giving up on the page.
            picked = cprog.split_page_by_table(samples, data, zones, ztimes,
                                               sample_sec)
            if picked is not None:
                bounds, chosen_t0 = picked
                notes.append(f"p{pno + 1}: zones {lo}-{hi} — the pumping data "
                             f"shows more breaks than there are zones, so the "
                             f"summary table's start times chose which "
                             f"{nz - 1} of them are zone boundaries")
        if bounds is None:
            fallback = cprog.table_split(ztimes, lo, hi, len(samples),
                                         sample_sec, span_min)
            if fallback is None:
                notes.append(f"p{pno + 1}: captioned 'Zones {lo}-{hi}' but "
                             f"neither the pumping data nor the summary times "
                             f"separate {nz} treatments, so the page is left "
                             f"whole rather than split onto the wrong zones")
                return whole(zr)
            bounds, zones = fallback
            by_table = True
            if len(zones) != nz:
                notes.append(f"p{pno + 1}: captioned 'Zones {lo}-{hi}' but the "
                             f"summary table times only cover zones "
                             f"{zones[0]}-{zones[-1]}; split on those")

        # Fit ONE clock origin for the page and read every zone off the chart's
        # axis from there. Stamping each zone with its own table entry and the
        # rest from the axis mixed two clocks in one well — stage 11 at 18:06
        # and stage 12 at 03:36. When the table drove the split the origin is
        # exact by construction: the first zone's printed start.
        offsets = [a * sample_sec / 60.0 for a, _b in bounds]
        if chosen_t0 is not None:
            # the cuts were matched to the printed times against this origin
            anchor = (chosen_t0, len(zones))
        elif by_table:
            anchor = (cprog.zone_start_minutes(ztimes, zones[0]), len(zones))
        else:
            anchor = cprog.anchor_t0(zones, offsets, ztimes)
            if anchor is None:
                # Nothing corroborated, but the chart still begins when its
                # first zone began. On a two-zone page there is no third time
                # to break the tie, and a page whose zones disagree by an hour
                # is still better placed on the clock than left at 00:00.
                first = cprog.zone_start_minutes(ztimes, zones[0])
                if first is not None:
                    anchor = (first, 1)
                    notes.append(f"p{pno + 1}: zones {lo}-{hi} — the printed "
                                 f"start times disagree with the chart's "
                                 f"spacing, so it is placed on the clock by "
                                 f"zone {zones[0]}'s start alone")
                elif ztimes:
                    notes.append(f"p{pno + 1}: zones {lo}-{hi} — no usable "
                                 f"start time in the summary table, so the "
                                 f"zones are split but timed from the chart's "
                                 f"own axis")
        # Only a CAPTIONED page's cuts are worth lending: this record belongs to
        # the page whose caption named the zones, and its uncaptioned twin
        # follows it.
        if borrowed is None and _last_progress[0] is not None and len(samples):
            _last_progress[0].update(
                {"cuts": [(a / len(samples), b / len(samples))
                          for a, b in bounds],
                 "zones": zones, "anchor": anchor})

    geom = getattr(meta, "geom", None)
    # The sheet's own "Job Date:" first, because the chart's only date is the
    # MView footer and that is when the chart was EXPORTED, not when the zones
    # ran — see cprog.sheet_job_date.
    sheet_date = cprog.job_date_for(all_times or {}, sheet_dates or {},
                                    pno, lo)
    page_date = (sheet_date or getattr(meta, "date", "")
                 or cprog.job_date(page) or "")
    out = []
    for j, (a, b) in enumerate(bounds):
        zone = zones[j] if j < len(zones) else zones[-1] + (j - len(zones) + 1)
        label = str(zone)
        md = _md(meta)
        md["stage"] = label
        # The footer date job_date() reads is the date MView EXPORTED the
        # chart, not the day the zone ran: 00082's footer says 10/11/2018 for
        # 28 zones the Treatment Summary grid dates 10/10, and 00087's zones
        # 1-3 ran on the 4th and were stamped the 5th. Where the grid prints a
        # Job Date for this zone, it is the authority.
        zentry = (calfrac_summary.zone_clock_for(zclocks, label)
                  if zclocks else None)
        zone_date = (zentry or {}).get("date") or page_date
        md["date"] = zone_date
        if not (zentry or {}).get("date") and sheet_date:
            # which END of the job this date names, for _calfrac_days: the
            # summary sheet prints the day the job STARTED, the MView footer
            # the day the chart was exported, which is the day it ended
            md["day_is"] = "start"
        # how many zones the page this came from was covering — a zone read off
        # a 12-zone overview is coarser than the same zone on its own chart
        md["zone_span"] = nz
        md["duration_min"] = (b - a) * sample_sec / 60.0
        # seconds from midnight of zone_date: the fitted origin (0 when the
        # table gave nothing usable) plus this zone's place on the axis
        secs = int(round((anchor[0] * 60 if anchor else 0) + a * sample_sec))
        md["start_time"] = (f"{secs // 3600 % 24:02d}:"
                            f"{secs % 3600 // 60:02d}:{secs % 60:02d}")
        if secs >= 24 * 3600 and zone_date:
            md["date"] = (datetime.strptime(zone_date, "%Y-%m-%d")
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


def _canyon_dates(doc, results, notes):
    """Date each Canyon chart from the report's printed interval summary.

    A Canyon chart page prints one date in its header — the day the JOB began,
    repeated on every interval page — and a time axis that carries the clock
    but not the day. On a job that runs a week that dates most intervals to
    day one: 17 of 00009's 25 charts claimed 2014-10-12 when the report's own
    TREATMENT INTERVAL SUMMARY dates them 10-13 and later. Any join on date,
    and any export a client sorts by date, is wrong by days.

    The summary prints each interval's start as a full timestamp, and our
    clock already agrees with it to within a couple of minutes (interval 9:
    00:49:22 read off the axis against a printed 00:47:50), so only the DAY is
    taken from it. An interval the summary does not print keeps the header
    date — there is nothing better to say about it.
    """
    if canyon_tables is None:
        return
    charts = [r for r in results if r.get("source") == "Canyon chart"
              and r["meta"].get("stage")]
    if not charts:
        return
    try:
        summary = canyon_tables.parse_interval_summary(doc)
    except Exception as e:                      # pragma: no cover - defensive
        notes.append(f"Canyon interval summary unreadable, so chart dates "
                     f"stay as the page header printed them — {e}")
        return
    if not summary or "Start Time" not in summary["columns"]:
        return
    ic = summary["columns"].index("Interval")
    sc = summary["columns"].index("Start Time")
    # A re-treated interval prints one row per attempt ("3 (attempt 1)",
    # "3 (attempt 2)") days apart, while the chart is titled with the bare
    # number — so keep every attempt and let the chart's own clock say which
    # one it is. 00204 re-attempts 3, 8, 11 and 26; taking the wrong row would
    # move those charts by one to four days.
    printed = {}
    for row in summary["rows"]:
        key = re.match(r"\d+", str(row[ic] or "").strip())
        stamp = str(row[sc] or "").strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})", stamp)
        if key and m:
            printed.setdefault(key.group(0), []).append(
                (m.group(1), int(m.group(2)) * 3600 + int(m.group(3)) * 60))
    if not printed:
        return
    fixed, unmatched = 0, []
    for r in charts:
        st = re.match(r"\d+", str(r["meta"]["stage"]))
        attempts = printed.get(st.group(0)) if st else None
        if not attempts:
            unmatched.append(str(r["meta"]["stage"]))
            continue
        ours_m = re.match(r"(\d{2}):(\d{2})", r["meta"].get("start_time") or "")
        if len(attempts) > 1 and ours_m:
            mine = int(ours_m.group(1)) * 3600 + int(ours_m.group(2)) * 60
            # nearest on the clock face, so a chart pumped at 15:48 does not
            # take the 07:14 re-attempt's day
            attempts = sorted(attempts, key=lambda a: min(
                abs(mine - a[1]), 24 * 3600 - abs(mine - a[1])))
        day, printed_secs = attempts[0]
        ours = re.match(r"(\d{2}):(\d{2})", r["meta"].get("start_time") or "")
        if ours:
            # a chart whose window opens either side of midnight from the
            # printed start belongs to the neighbouring day
            delta = (int(ours.group(1)) * 3600 + int(ours.group(2)) * 60
                     - printed_secs)
            if delta < -12 * 3600:
                day = (datetime.strptime(day, "%Y-%m-%d")
                       + timedelta(days=1)).strftime("%Y-%m-%d")
            elif delta > 12 * 3600:
                day = (datetime.strptime(day, "%Y-%m-%d")
                       - timedelta(days=1)).strftime("%Y-%m-%d")
        if r["meta"].get("date") != day:
            r["meta"]["date"] = day
            fixed += 1
    if fixed:
        notes.append(f"{fixed} Canyon chart(s) re-dated from the printed "
                     f"interval summary — the chart pages all carry the job's "
                     f"start date, not the day the interval ran.")
    if unmatched:
        notes.append(f"interval(s) {', '.join(unmatched[:8])} are not in the "
                     f"printed interval summary, so their charts keep the "
                     f"date the page header prints.")


def _day_shift(day, ours_secs, printed_secs):
    """`day` moved to the side of midnight our own clock sits on."""
    delta = ours_secs - printed_secs
    if delta < -12 * 3600:
        return (datetime.strptime(day, "%Y-%m-%d")
                + timedelta(days=1)).strftime("%Y-%m-%d")
    if delta > 12 * 3600:
        return (datetime.strptime(day, "%Y-%m-%d")
                - timedelta(days=1)).strftime("%Y-%m-%d")
    return day


# How far a printed CalFrac date may be moved to make the well's clock run
# forwards. One day covers a missed midnight; three leaves room for a page
# whose stamp is a couple of days out without letting the search invent a
# fortnight-long job out of a fortnight-long one that was already right.
_CALFRAC_MAX_DAY_SHIFT = 3


def _calfrac_day_fit(days, secs):
    """Fewest whole-day moves that make (day, time) strictly increasing.

    -> corrected day ordinals, or None if no assignment within
    ±_CALFRAC_MAX_DAY_SHIFT works.

    Zones are pumped in ascending order, so zone N+1's instant is after zone
    N's; that is the report's own statement, printed as the order of the
    Treatment Summary's columns. When the dates the pages print contradict it,
    something has to move, and the honest choice is the one that contradicts
    the fewest printed pages. On 00119 the twelve zones of page 92 are stamped
    05-01 and run 13:07-23:52, and the fifteen zones of page 99 are stamped
    05-01 and run 00:41-13:21: one of the two blocks is a day out. Moving the
    twelve back to 04-30 costs twelve pages, moving the fifteen on to 05-02
    costs fifteen — and BCER files exactly those twelve on 04-30.
    """
    n = len(days)
    shifts = range(-_CALFRAC_MAX_DAY_SHIFT, _CALFRAC_MAX_DAY_SHIFT + 1)
    cost = [{s: abs(s) for s in shifts}]
    came = [{}]
    for i in range(1, n):
        row, back = {}, {}
        for s in shifts:
            here, best, arg = days[i] + s, None, None
            for t, c in cost[i - 1].items():
                there = days[i - 1] + t
                if here > there or (here == there and secs[i] > secs[i - 1]):
                    if best is None or c < best:
                        best, arg = c, t
            if arg is not None:
                row[s], back[s] = best + abs(s), arg
        if not row:
            return None                 # the printed dates cannot be reconciled
        cost.append(row)
        came.append(back)
    s = min(cost[-1], key=lambda k: (cost[-1][k], abs(k)))
    out = [0] * n
    out[-1] = s
    for i in range(n - 1, 0, -1):
        out[i - 1] = came[i][out[i]]
    return [days[i] + out[i] for i in range(n)]


def _calfrac_days(results, notes):
    """Put a CalFrac well's stages back in order across a midnight.

    THESE REPORTS DATE A PAGE, NOT A STAGE. The MView footer is the date the
    chart was exported and the header carries the day the sheet covers, so a
    well that pumped through midnight can print one day over stages that ran
    on two — 00017's eighteen zones all say 3/9/2015 though zones 1-11 ran on
    the 8th — or stamp one block a day late while the next block is right —
    00119 dates zones 25-36 05-01 when they ran 04-30, so its exported clock
    jumps from 23:52 back to 00:41 and calls the second instant earlier.
    Carmine's report on the 2018 books is the same shape: right up to a stage,
    then a day out for every stage after it.

    Nothing outside the file is needed to see this. The zones are pumped in
    order, so their instants increase; where the export says otherwise the
    dates are wrong, whatever the pages print.

    Two repairs, both anchored on what the document actually prints:

      * where the pages print MORE THAN ONE date, they are dating their own
        contents and only some of them are out — move the fewest of them
        (_calfrac_day_fit).
      * where every page prints the SAME date, that date is a job stamp with
        nothing to say about which zone ran when. An MView export is made when
        the job is done, so the stamp belongs to the LAST day the well pumped;
        earlier days count back from it.

    A well that prints no clock is not touched: there is no order to restore
    and the stages are honestly undated.
    """
    stages, order = {}, []
    for r in results:
        if r.get("source") != "CalFrac chart":
            continue
        md = r.get("meta", {})
        if md.get("multi_zone"):
            continue                    # a zone range, not a stage
        st = str(md.get("stage") or "").strip()
        m = re.match(r"\d+", st)
        secs = _hms(md.get("start_time"))
        if not m or not md.get("date") or secs is None or \
                (md.get("start_time") or "") == "00:00:00":
            continue                    # no clock, or no day, or not a zone
        if st not in stages:
            order.append(st)
        stages.setdefault(st, []).append(r)
    if len(order) < 2:
        return
    order.sort(key=lambda s: (int(re.match(r"\d+", s).group(0)), s))
    try:
        days = [datetime.strptime(stages[s][0]["meta"]["date"],
                                  "%Y-%m-%d").toordinal() for s in order]
    except ValueError:
        return
    secs = [_hms(stages[s][0]["meta"]["start_time"]) for s in order]

    # relative day of each stage, counted off the clock alone: a start time
    # earlier than the one before it is a midnight
    step, rel = 0, []
    for i, c in enumerate(secs):
        if i and c < secs[i - 1]:
            step += 1
        rel.append(step)

    if len(set(days)) == 1 and step > 0:
        # One date over a well that pumped through midnight says nothing about
        # which zone ran when — but it does say which END of the job it names.
        # A summary sheet's "Job Date:" is the day the job started, so the
        # zones count FORWARD from it; the MView footer is an export stamp,
        # made when the job was done, so they count BACK from it.
        starts = all(stages[s][0]["meta"].get("day_is") == "start"
                     for s in order)
        anchor = days[0] if starts else days[-1] - rel[-1]
        want = [anchor + r for r in rel]
        why = (f"every page dates this well "
               f"{stages[order[0]][0]['meta']['date']}, but its own start "
               f"times cross midnight {step} time{'s' if step > 1 else ''} — "
               + ("that is the summary's Job Date, the day the job began, so "
                  "the later zones run on from it"
                  if starts else
                  "an MView stamp is the export date, so it is the LAST day "
                  "pumped and the earlier zones count back from it"))
    else:
        want = _calfrac_day_fit(days, secs)
        if want is None:
            notes.append("the dates these charts print cannot be put in "
                         "pumping order by whole days, so every stage keeps "
                         "the date its own page prints — read the times with "
                         "care where the well ran through midnight.")
            return
        why = ("their pages date the sheet rather than the zone, and the "
               "printed start times run backwards across the boundary")

    moved = []
    for i, st in enumerate(order):
        if want[i] == days[i]:
            continue
        day = datetime.fromordinal(want[i]).strftime("%Y-%m-%d")
        for r in stages[st]:
            r["meta"]["date"] = day
        moved.append(st)
    if moved:
        notes.append(f"{len(moved)} stage(s) re-dated so the well's clock runs "
                     f"forwards (zones {', '.join(moved[:8])}"
                     f"{', …' if len(moved) > 8 else ''}) — {why}.")


def _hms(t):
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(t or ""))
    if not m:
        return None
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
            + int(m.group(3) or 0))


def _trican_clock(doc, results, notes):
    """Date and clock a Trican layout-A chart from its own STAGE INFORMATION
    page.

    These charts read for elapsed minutes only — trican_charts.time_axis takes
    the "Elapsed Time (min)" strip below the frame — so the template exported
    with no date and no start time at all: measured, 0 of 39 stages on 00005
    and 0 of 28 on 00317. The report prints the answer on the page after each
    chart, in the As-Pumped "Start Time" cell, and trican2 already reads that
    table for everything else.

    Only fills what is empty. A chart that somehow carries its own clock keeps
    it — nothing here is a correction, unlike the STEP pass below, because
    there is no second reading to disagree with.
    """
    tri = [r for r in results
           if r.get("type") == "series"
           and str(r.get("source") or "").startswith("Trican")
           and str(r["meta"].get("stage") or "").strip()]
    if not tri:
        return
    try:
        clocks = trican2.stage_clock(doc)
    except Exception as e:                      # pragma: no cover - defensive
        notes.append(f"Trican STAGE INFORMATION unreadable, so its charts "
                     f"keep no clock — {e}")
        return
    if not clocks:
        return
    dated = clocked = resolved = 0
    how = ""
    chart, differ = 0, []
    for r in tri:
        md = r["meta"]
        m = re.match(r"\d+", str(md.get("stage")).strip())
        if not m:
            continue
        entry = clocks.get(int(m.group(0)))
        if not entry:
            continue
        if md.get("clock_chart"):
            # The chart clocked itself from its own Clock Time axis. The
            # table supplies the DATE (the axis prints none) and a second
            # opinion on the time, and where the two differ the chart is
            # kept: 00041 p117 prints "Start Time 12:00" under a chart
            # whose axis runs 06:22-07:25, and the day sheet's "End Time
            # 7:24 am" sides with the chart. p73's sheet says 21:40 for a
            # chart that opens at 21:38 — the sheet times the STAGE, the
            # axis times the chart, and the samples are the chart's.
            chart += 1
            cs = _secs(md["start_time"])
            ts = _secs(entry["start"]) if entry["start"] else None
            # What the SHEET says about this stage, kept beside what the
            # chart says. _trican_continuous needs it: the sheet is the only
            # statement of how long the stage actually ran, and a chart that
            # opens partway through one (stage 1, every time — see
            # trican2.stage_clock) cannot say so itself.
            if entry["start"]:
                md["sheet_start"] = entry["start"]
            if entry["date"]:
                md["date"] = _nearest_date(entry["date"], ts, cs)
                dated += 1
            if ts is not None:
                off = abs((cs - ts + 43200) % 86400 - 43200)
                if off > 120:
                    differ.append(f"stage {m.group(0)} (sheet {entry['start'][:5]}, "
                                  f"chart {md['start_time'][:5]})")
                    md.setdefault("warnings", []).append(
                        f"the STAGE INFORMATION sheet's Start Time "
                        f"{entry['start'][:5]} is {_fmt_off(off)} off the "
                        f"chart's own axis; the chart is kept")
            continue
        took = False
        if not md.get("date") and entry["date"]:
            md["date"] = entry["date"]
            dated += 1
            took = True
        if (md.get("start_time") or "00:00:00") == "00:00:00" \
                and entry["start"] != "00:00:00":
            md["start_time"] = entry["start"]
            clocked += 1
            took = True
        # A 12-hour table read through a rule is the table's time, not the
        # chart's, and the export has to say so (00015, #639).
        if took and entry.get("resolved"):
            resolved += 1
            how = entry["resolved"]
            md.setdefault("warnings", []).append("clock: " + how)
    if chart:
        notes.append(f"{chart} Trican chart(s) clocked from their own Clock "
                     f"Time axis (24-hour, printed above the plot) and dated "
                     f"from the STAGE INFORMATION page that follows each one"
                     + (f"; the sheet's Start Time differs from the chart on "
                        f"{len(differ)} of them and the chart is kept: "
                        + ", ".join(differ[:6])
                        + (", …" if len(differ) > 6 else "") if differ else ""))
    if clocked or (dated > chart):
        notes.append(f"{max(dated - chart, clocked)} Trican chart(s) dated and "
                     f"clocked from the STAGE INFORMATION page that follows "
                     f"each one"
                     + (f" — {resolved} of them from a {how}; these times are "
                        f"the table's, not the chart's" if resolved else ""))


def _route_b_notes(notes):
    """A layout-B reader's notes -> (the axis drops, the stage's own notes).

    "<label>: <axis> axis unreadable" is the one shape that means a channel
    was left out; everything else the reader says is about a channel it
    exported and is shown on that stage, not summed across the file.
    """
    drops, mine = [], []
    for n in notes:
        (drops if "axis unreadable" in str(n) else mine).append(str(n))
    return drops, mine


def _secs(hms):
    """'HH:MM:SS' -> seconds since midnight."""
    h, m, s = (str(hms).split(":") + ["0", "0"])[:3]
    return int(h) * 3600 + int(m) * 60 + int(float(s))


def _fmt_off(seconds):
    return (f"{seconds / 3600:.1f} h" if seconds >= 3600
            else f"{int(round(seconds / 60))} min")


def _nearest_date(date_str, table_s, chart_s):
    """The day the chart's clock falls on, given the sheet's own date and
    time for the same stage -> 'YYYY-MM-DD'.

    The axis prints hours and minutes and no day. The sheet's date is right
    to the day and its time to within the 12-hour fold, so of yesterday,
    the sheet's day and tomorrow, the one that puts the chart's time
    nearest the sheet's is the chart's day: a chart opening 23:58 under a
    sheet dated the 13th at 00:01 opened on the 12th.
    """
    if table_s is None:
        return date_str
    try:
        d0 = datetime.fromisoformat(str(date_str)[:10])
    except ValueError:
        return date_str
    ref = d0 + timedelta(seconds=table_s)
    best = None
    for k in (0, -1, 1):
        d = d0 + timedelta(days=k)
        gap = abs((d + timedelta(seconds=chart_s) - ref).total_seconds())
        if best is None or gap < best[0] - 1:
            best = (gap, d.date().isoformat())
    return best[1]


def _abs_start(r):
    """A series' clock as a datetime, or None when it has no real one.

    Dated at 00:00:00 means "no time read" everywhere but on a chart that
    clocked itself (clock_chart), where midnight is a time like any other.
    """
    md = r.get("meta") or {}
    d, st = md.get("date"), md.get("start_time") or ""
    if not d or not st:
        return None
    if st == "00:00:00" and not md.get("clock_chart"):
        return None
    try:
        return datetime.fromisoformat(str(d)[:10]) + timedelta(seconds=_secs(st))
    except ValueError:
        return None


def _sample_sec(r):
    s = r.get("samples")
    try:
        return float(s[1] - s[0]) if len(s) > 1 else 1.0
    except (TypeError, IndexError):
        return 1.0


def _sheet_head_gap(cont_t0, stage_r):
    """Seconds of a CONTINUOUS chart's lead-in that belong to the first
    stage, by that stage's OWN sheet. 0.0 when the sheet says nothing, or
    says the stage began where its chart does.

    00218's stage 1: the sheet reads 20:31 -> 01:28, 296.8 min, and the
    chart page plots elapsed 195 -> 302 with a clock axis opening at 23:46.
    Those 195 minutes are stage 1 and are printed on no stage page. Capped
    at the lead-in the overview actually has, and never run past the
    chart's own start.
    """
    if stage_r is None:
        return 0.0
    st = _abs_start(stage_r)
    sheet = stage_r["meta"].get("sheet_start")
    if st is None or cont_t0 is None or not sheet:
        return 0.0
    # The sheet prints a time and no day; the stage's date is the chart's.
    want = _nearest_date(st.date().isoformat(), _secs(st.strftime("%H:%M:%S")),
                         _secs(sheet))
    try:
        sheet_t = datetime.fromisoformat(want) + timedelta(seconds=_secs(sheet))
    except ValueError:
        return 0.0
    if sheet_t >= st:
        return 0.0                      # the sheet agrees, or starts later
    return max(0.0, (st - max(sheet_t, cont_t0)).total_seconds())


def _stage_windows(tri):
    """(start, end, meta, series) for every non-continuous chart that has a
    clock, in time order. Rebuilt rather than patched after a splice, so the
    windows and the samples can never drift apart."""
    out = []
    for r in tri:
        if r["meta"].get("continuous"):
            continue
        t0 = _abs_start(r)
        if t0 is None:
            continue
        out.append((t0, t0 + timedelta(
            seconds=len(r["samples"]) * _sample_sec(r)), r["meta"], r))
    out.sort(key=lambda s: s[0])
    return out


def first_of(stages):
    return stages[0][3] if stages else None


def last_of(stages):
    return stages[-1][3] if stages else None


def _splice_continuous_edge(c, stage_r, at_front, secs, notes):
    """Move `secs` seconds off the edge of a CONTINUOUS chart onto the stage
    chart it runs into. Returns the minutes moved, or 0.0.

    The minutes are the only copy of themselves: 00218's stage 1 ran 296.8
    min by its own sheet (20:31 -> 01:28) and its chart page plots elapsed
    195 -> 302, the last 107 of them. The first 195 minutes of that stage
    are printed nowhere but on the CONTINUOUS page. Read from the stage
    chart alone, stage 1 exports 96 min and 200 minutes of a real stage are
    simply gone — which is what Carmine has been reporting as truncation.

    They arrive coarser: the CONTINUOUS page draws 19.7 h across the same
    width the stage page gives 107 min, so a pixel is about a minute rather
    than a second. That is a real difference and the stage says so in its
    warnings rather than presenting the join as seamless.
    """
    import numpy as np
    sec_a = _sample_sec(stage_r)
    sec_c = _sample_sec(c)
    cs = np.asarray(c["samples"], float)
    if secs <= 0 or not len(cs):
        return 0.0
    # The window being taken, in the CONTINUOUS chart's own elapsed seconds.
    lo, hi = (0.0, secs) if at_front else (len(cs) * sec_c - secs, len(cs) * sec_c)
    grid = np.arange(0.0, secs, sec_a)
    if not len(grid):
        return 0.0
    src = grid + lo
    lead = {}
    for label in stage_r["data"]:
        v = c["data"].get(label)
        if v is None:
            # A channel the stage plots and the overview does not. Blank, not
            # zero: a concentration that reads 0 for three hours is a claim.
            lead[label] = np.full(len(grid), np.nan)
            continue
        vv = np.asarray(v, float)
        n = min(len(cs), len(vv))
        fin = np.isfinite(vv[:n])
        lead[label] = (np.interp(src, cs[:n][fin], vv[:n][fin],
                                 left=np.nan, right=np.nan)
                       if fin.any() else np.full(len(grid), np.nan))
    sa = np.asarray(stage_r["samples"], float)
    if at_front:
        stage_r["samples"] = np.concatenate([grid, sa + secs])
        stage_r["data"] = {l: np.concatenate([lead[l], np.asarray(v, float)])
                           for l, v in stage_r["data"].items()}
        t0 = _abs_start(stage_r) - timedelta(seconds=secs)
        stage_r["meta"]["start_time"] = t0.strftime("%H:%M:%S")
        stage_r["meta"]["date"] = t0.date().isoformat()
        # The stage now starts where its SHEET says it does, so the warning
        # that its chart's axis disagreed with the sheet is stale — and a
        # stale warning is worse than none, because it says the start is
        # wrong when the splice is exactly what made it right. Cleared only
        # when the new start actually agrees; if it still does not, the
        # warning is still true and stays.
        keep = []
        for w in stage_r["meta"].get("warnings", []):
            m = re.search(r"STAGE INFORMATION sheet's Start Time (\d{2}:\d{2})", str(w))
            if m:
                off = abs((_secs(m.group(1) + ":00") - _secs(
                    stage_r["meta"]["start_time"]) + 43200) % 86400 - 43200)
                if off <= 300:
                    continue
            keep.append(w)
        stage_r["meta"]["warnings"] = keep
    else:
        end = (sa[-1] + sec_a) if len(sa) else 0.0
        stage_r["samples"] = np.concatenate([sa, grid + end])
        stage_r["data"] = {l: np.concatenate([np.asarray(v, float), lead[l]])
                           for l, v in stage_r["data"].items()}
    stage_r["meta"]["duration_min"] = len(stage_r["samples"]) * sec_a / 60.0
    mins = secs / 60.0
    stage_r["meta"].setdefault("warnings", []).append(
        f"the {'first' if at_front else 'last'} {mins:.0f} min of this stage "
        f"are not on its own chart — they are taken from the CONTINUOUS page "
        f"(p{c['page']}), which is the only page that plots them. That page "
        f"draws the whole job at about a minute per pixel, so these minutes "
        f"are coarser than the rest of the stage")
    return mins


def _trican_continuous(results, notes):
    """Drop a Trican CONTINUOUS chart when the stage charts already carry
    every minute of it.

    00041 closes with six "CONTINUOUS PRESSURES, RATES, AND CONCENTRATIONS"
    pages: the whole job re-plotted end to end — 18.5 h and 12 h for stages
    1-30 at 65 s per pixel, then stages 31-34 again one each. They carry no
    stage number, so they exported as six nameless stages with no clock,
    and FracView laid all 33 hours of them after stage 34. Every minute of
    them is on a stage chart at eight times the resolution.

    Clocked from its own axis and dated from the stage whose start it
    matches, a continuous chart that the stage windows cover is dropped and
    said so. One that covers minutes no stage chart has — or that could not
    be clocked — stays, because then it is the only copy.
    """
    tri = [r for r in results if r.get("type") == "series"
           and str(r.get("source") or "").startswith("Trican")]
    cont = [r for r in tri if r["meta"].get("continuous")]
    if not cont:
        return
    stages = _stage_windows(tri)
    dropped, kept, spliced = [], [], []
    for r in cont:
        md = r["meta"]
        why = None
        if not md.get("clock_chart") or not stages:
            why = "no clock could be read for it"
        else:
            cs = _secs(md["start_time"])
            near = min(stages, key=lambda s: abs(
                (cs - _secs(s[2]["start_time"]) + 43200) % 86400 - 43200))
            gap = abs((cs - _secs(near[2]["start_time"]) + 43200) % 86400 - 43200)
            # Half an hour was far too tight, and it is the wrong quantity.
            #
            # What this bound protects is _nearest_date, which picks between
            # yesterday, today and tomorrow — so it only becomes ambiguous
            # as the gap approaches TWELVE hours, not thirty minutes. And a
            # whole-job re-plot legitimately opens hours before stage 1:
            # 00218's CONTINUOUS page starts at 20:32 and its first stage
            # chart opens at 23:46, 3.2 h later. Under the old bound it could
            # not be dated, so it could not be measured against the stages,
            # so it was kept — and it arrived in the list as a nameless last
            # stage carrying the entire 19.7 h job, 70,800 rows of it.
            if gap > CONTINUOUS_DATE_S or not near[2].get("date"):
                why = (f"no stage chart opens within "
                       f"{CONTINUOUS_DATE_S / 3600:.0f} h of it, so it has no day")
            else:
                md["date"] = _nearest_date(near[2]["date"],
                                           _secs(near[2]["start_time"]), cs)
                t0 = _abs_start(r)
                t1 = t0 + timedelta(seconds=len(r["samples"]) * _sample_sec(r))
                # The minutes at either END of this chart that no stage
                # chart carries belong to the stage they run into: give them
                # to it rather than keeping the whole overview for their
                # sake. Done before the coverage test, because doing it is
                # what makes the overview droppable — and it is the only way
                # those minutes reach the CSV at all, since the stage's own
                # page does not plot them (see _splice_continuous_edge).
                # The FRONT of the chart only, and only as far back as the
                # stage's own sheet says the stage began.
                #
                # The sheet is the only statement of a stage's real extent,
                # and without it a splice is a guess. Minutes running past
                # the LAST stage have no such evidence — that is the job
                # winding down and belongs to no stage — so they keep the
                # overview instead, which is what they did before.
                secs = _sheet_head_gap(t0, first_of(stages))
                target = first_of(stages)
                if secs > CONTINUOUS_JOIN_S and target is not None:
                    got = _splice_continuous_edge(r, target, True, secs, notes)
                    if got:
                        spliced.append((r["page"],
                                        target["meta"].get("stage") or "?",
                                        got, True))
                if spliced:
                    stages = _stage_windows(tri)
                    t0 = _abs_start(r)
                covered, cursor = 0.0, t0
                for a, b, _m, _r in stages:
                    a, b = max(a, cursor), min(b, t1)
                    if b > a:
                        covered += (b - a).total_seconds()
                        cursor = b
                frac = covered / max(1.0, (t1 - t0).total_seconds())
                if frac >= 0.9:
                    dropped.append(r)
                else:
                    miss = ((t1 - t0).total_seconds() - covered) / 60.0
                    why = f"{miss:.0f} min of it are on no stage chart"
        if why:
            kept.append((r["page"], why))
    for pg, st, mins, at_front in spliced:
        notes.append(
            f"stage {st}: {mins:.0f} min added to its "
            f"{'start' if at_front else 'end'} from the CONTINUOUS chart on "
            f"p{pg} — the stage ran longer than its own chart plots, and that "
            f"page is the only one carrying those minutes. They are drawn at "
            f"about a minute per pixel there, so they are coarser than the "
            f"rest of the stage")
    if dropped:
        for r in dropped:
            results.remove(r)
        pages = ", ".join(f"p{r['page']}" for r in dropped)
        notes.append(f"{len(dropped)} CONTINUOUS chart(s) not exported ({pages}): "
                     f"the same job re-plotted end to end, and every minute of "
                     f"them is on a stage chart at higher resolution")
    for pg, why in kept:
        notes.append(f"p{pg}: CONTINUOUS chart kept as a stage of its own — {why}")


# How far a CONTINUOUS chart's clock may sit from the nearest stage chart's
# and still be dated from it. The real limit is the 12-hour fold _nearest_date
# resolves; six hours is comfortably inside it and covers a whole-job re-plot
# that opens before the first stage.
CONTINUOUS_DATE_S = 6 * 3600.0
# Minutes of a CONTINUOUS chart that sit outside every stage window, and are
# therefore the only copy of themselves, may be spliced onto the stage they
# run into. Wider than a stage's own slack and far narrower than idle time
# between stages, which belongs to no stage and must not be handed to one.
CONTINUOUS_JOIN_S = 120.0

HANDOVER_MIN_S = 30.0      # shorter than this is clock rounding, not a tail
HANDOVER_TOL = 0.05        # of the channel's own range over the stage
HANDOVER_SEARCH_S = 900.0  # how far a start filed to the minute may sit from the window
HANDOVER_SELF_S = 60.0     # and one the chart printed itself: the label's own precision
HANDOVER_K = 900           # samples of B's head compared when searching for the lag


def _lag_scores(a, b, offs, K):
    """A[off:off+K] against B[:K] for every off in `offs` -> (channels
    compared, channels agreeing, mean gap as a fraction of range), one
    entry per off.

    One vectorised pass per channel over a sliding window of A, so a
    fifteen-minute search at one-second lags costs milliseconds and not
    the twenty seconds a loop of scores did. A channel says nothing at an
    off where fewer than ten samples are finite on both sides, and nothing
    at all when it is flat over the stage.
    """
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    offs = np.asarray(list(offs), int)
    L = len(offs)
    compared = np.zeros(L, int)
    agreed = np.zeros(L, int)
    gapsum = np.zeros(L, float)
    for label, va in a["data"].items():
        vb = b["data"].get(label)
        if vb is None:
            continue
        xa = np.asarray(va, float)
        xb = np.asarray(vb, float)[:K]
        if len(xa) < K or len(xb) < K:
            continue
        fin = xa[np.isfinite(xa)]
        scale = float(fin.max() - fin.min()) if fin.size else 0.0
        if scale <= 0:
            continue
        valid = (offs >= 0) & (offs <= len(xa) - K)
        if not valid.any():
            continue
        W = sliding_window_view(xa, K)[offs[valid]]
        D = np.abs(W - xb[None, :])
        cnt = np.isfinite(D).sum(axis=1)
        g = np.nansum(D, axis=1) / np.maximum(cnt, 1) / scale
        ok = cnt >= 10
        compared[valid] += ok
        agreed[valid] += ok & (g <= HANDOVER_TOL)
        gapsum[valid] += np.where(ok, g, 0.0)
    return compared, agreed, gapsum / np.maximum(compared, 1)


def _hand_over_tails(results, notes):
    """Where one chart runs on into the next and the next re-plots those
    minutes, cut the first at the second's start.

    Every Trican layout-A chart on 00041 runs 4-10 minutes past its sheet's
    Finish Time — the sleeves are opened with the pumps still running, and
    the page keeps plotting into the next stage — and the next chart opens
    on the same minutes: stage 1's last 4.3 min and stage 2's first 4.3 are
    the same pressures to 1%. Exported whole, every stage overlapped the one
    after it and FracView drew both (#645, the "still some overlap").

    The cut is made only where the samples say the two charts agree over the
    overlap (mean gap under 5% of the channel's range, on two thirds of the
    channels both plot). Where they disagree the overlap is real or a clock
    is wrong; that stays as printed and is said on the stage.

    A clock a little wrong is the common case, and it is knowable. 00180's
    STEP charts are placed from the Daily Stage Summary, which files each
    start to the MINUTE and files the stage's start, not the instant the
    plot window opens: stage 6's head was the same minutes as stage 5's
    tail drawn half a minute later, so at lag zero they disagreed and both
    were drawn. Where lag zero fails, the lag that makes the two charts the
    same is searched for — five minutes either way for a start filed to the
    minute, one minute for a chart that printed its own clock — and the
    later chart is moved by it. The overlap is the only place the page says
    to the second where a chart sits; the filed minute is kept as the bound.
    """
    import numpy as np
    per = {}
    for r in results:
        if r.get("type") != "series" or r["meta"].get("continuous"):
            continue
        t0 = _abs_start(r)
        smp = r.get("samples")
        if t0 is None or smp is None or len(smp) == 0:
            continue
        per.setdefault(str(r.get("source") or ""), []).append((t0, r))
    trimmed, differ, moved = [], [], []
    for src, items in per.items():
        items.sort(key=lambda x: x[0])
        prev = None
        centre = 0                        # the last lag found: the drift is smooth
        for tb, b in items:
            if prev is None:
                prev = (tb, b)
                continue
            ta, a = prev
            prev = (tb, b)
            sec = _sample_sec(a)
            n_a, n_b = len(a["samples"]), len(b["samples"])
            end_a = ta + timedelta(seconds=n_a * sec)
            ov = (end_a - tb).total_seconds()
            if ov < HANDOVER_MIN_S:
                continue

            sb = b["meta"].get("stage") or "?"
            off0 = int(round((tb - ta).total_seconds() / sec))
            keep = int(60.0 / sec)                       # a minute of A must remain
            lag, best = 0, None
            k0 = min(n_a - off0, n_b)
            if off0 >= keep and k0 >= 10:
                c, g, gp = _lag_scores(a, b, [off0], k0)
                if c[0]:
                    best = (g[0] * 3 >= c[0] * 2, g[0] / c[0], -gp[0], off0, k0, c[0])
            if best is None or not best[0]:
                # Searched around the lag the previous pair settled on, not
                # around zero: on 00180 the windows sit 2-4 min further from
                # each filed start than the one before (the charts' own clock
                # and the filed minutes disagree by a few percent), so by the
                # fourth stage of a run the lag is past a search centred on
                # the filed time, and the run broke into two chains anchored
                # 17 minutes apart. Following the drift keeps one chain.
                reach = HANDOVER_SELF_S if b["meta"].get("clock_chart") else HANDOVER_SEARCH_S
                reach = int(reach / sec)
                mid = off0 + (0 if b["meta"].get("clock_chart") else int(round(centre / sec)))
                back = min(reach, mid - keep)
                fwd = min(reach, n_a - mid - keep)
                K = min(n_b, n_a - (mid + fwd), HANDOVER_K)
                if back >= 0 and fwd >= 0 and K >= 10:
                    offs = np.arange(mid - back, mid + fwd + 1)
                    c, g, gp = _lag_scores(a, b, offs, K)
                    ok = (c > 0) & (g * 3 >= c * 2)
                    ok[offs == off0] = False
                    if ok.any():
                        frac = np.where(c > 0, g / np.maximum(c, 1), 0.0)
                        order = np.lexsort((-np.abs(offs - off0), -gp, frac))   # last key major
                        i = next(j for j in order[::-1] if ok[j])
                        lag = int((offs[i] - off0) * sec)
                        best = (True, frac[i], -gp[i], int(offs[i]), min(n_a - int(offs[i]), n_b), int(c[i]))
            if best is None:
                centre = 0
                continue
            ok_, _frac, _gap, off, k, compared = best
            centre = lag if ok_ else 0
            if not ok_:
                a["meta"].setdefault("warnings", []).append(
                    f"overlaps stage {sb} by {ov / 60:.1f} min and the two "
                    f"charts disagree there — one clock is wrong, or the "
                    f"stages overlap for real; both kept as printed")
                differ.append((a["meta"].get("stage") or "?", sb, ov))
                continue
            if lag:
                was = b["meta"].get("start_time")
                tb = tb + timedelta(seconds=lag)
                b["meta"]["start_time"] = tb.strftime("%H:%M:%S")
                b["meta"]["date"] = tb.date().isoformat()
                b["meta"].setdefault("warnings", []).append(
                    f"start moved {lag:+d} s ({was[:8]} → {tb:%H:%M:%S}) to line "
                    f"up with stage {a['meta'].get('stage') or '?'}'s chart, "
                    f"which re-plots the same minutes; the filed start is to "
                    f"the minute and this is where the window opens")
                moved.append((sb, lag))
                prev = (tb, b)
                ov = (end_a - tb).total_seconds()
            # Keep what is being handed over, beside the stage rather than in
            # it. The export still cuts here — those minutes belong to the next
            # chart and must not be written twice — but the CHART was ending
            # before the page it came from did, and against the printed page
            # that reads as data loss. It is not; it is a handover. Carried as
            # its own series so nothing downstream can mistake it for the
            # stage's own samples, and drawn greyed with the stage it went to.
            tail_s = a["samples"][off:]
            if len(tail_s):
                a["handover"] = {
                    "to": sb,
                    "samples": tail_s,
                    "data": {l: v[off:] for l, v in a["data"].items()},
                }
            # A stage cannot re-plot itself.
            #
            # The pairing walks charts in time order within a source group and
            # names the handover after b's stage. When two charts carry the
            # SAME stage label, a can hand its data to a chart that is its own
            # stage: 00028 p29 was cut to 61 samples with "the chart runs on
            # into stage 7, whose own chart re-plots those minutes" — and the
            # chart it meant was p30, stage 7 as well. The export then holds a
            # one-minute stub and a near-complete chart, both labelled 7, and
            # the stub is the one that surfaces. Carmine read that as "not
            # picking up stage 7" (#654), and stage 29 went the same way (#657,
            # p73 cut to 88 samples handing 53.4 min to p74).
            #
            # This is an invariant, not a threshold: whatever else is true, a
            # chart handing over to its own stage number is a mis-pairing. Only
            # when BOTH labels are known — two unlabelled charts are not
            # evidence of anything, and refusing those would suppress real
            # handovers on files that print no stage numbers.
            sa = a["meta"].get("stage") or ""
            if sa and sb and str(sa) == str(sb):
                a["meta"].setdefault("warnings", []).append(
                    f"overlaps a second chart also labelled stage {sb} by "
                    f"{ov / 60:.1f} min and the handover was refused: a stage "
                    f"cannot re-plot itself, so these are two charts of the "
                    f"same stage; both kept as printed")
                differ.append((sa, sb, ov))
                continue
            a["samples"] = a["samples"][:off]
            a["data"] = {l: v[:off] for l, v in a["data"].items()}
            a["meta"]["duration_min"] = off * sec / 60.0
            a["meta"].setdefault("warnings", []).append(
                f"last {ov / 60:.1f} min not exported here: the chart runs "
                f"on into stage {sb}, whose own chart re-plots those "
                f"minutes (same values), so the export hands over where "
                f"the next chart begins")
            trimmed.append((a["meta"].get("stage") or "?", ov))
    if moved:
        big = max(abs(l) for _s, l in moved)
        notes.append(f"{len(moved)} chart start(s) moved by up to {big} s to line "
                     f"up with the chart before, which re-plots the same minutes "
                     f"— the filed start is to the minute, and the overlap says "
                     f"to the second where the window opens"
                     + (". A move that large is a run of charts whose own clock "
                        "and the filed starts drift apart by a few percent; the "
                        "charts' own spacing is kept, anchored on the first "
                        "chart of the run at its filed start" if big > 600 else ""))
    if trimmed:
        total = sum(o for _s, o in trimmed) / 60.0
        notes.append(f"{len(trimmed)} chart(s) ran on into the next stage and "
                     f"were cut where the next chart begins — {total:.0f} min "
                     f"in all, every minute of it re-plotted on the next "
                     f"chart with the same values, so nothing is lost and "
                     f"nothing is exported twice")
    if differ:
        notes.append(f"{len(differ)} pair(s) of charts overlap and disagree "
                     f"there, kept as printed: "
                     + ", ".join(f"{a}→{b} ({o / 60:.1f} min)" for a, b, o in differ[:8])
                     + (", …" if len(differ) > 8 else ""))


_TOTALS_START = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})")
_TOTALS_START_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})")


def _totals_start(cell):
    """A Totals row's Start time -> (date, HH:MM:SS) or None. "6/1/19 0:23"
    as the 2019 sheets print it, or already ISO."""
    m = _TOTALS_START.search(str(cell or ""))
    if m:
        mo, d, y, hh, mm = (int(x) for x in m.groups())
        if y < 100:
            y += 2000                            # "6/1/19"
    else:
        m = _TOTALS_START_ISO.search(str(cell or ""))
        if not m:
            return None
        y, mo, d, hh, mm = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}", f"{hh:02d}:{mm:02d}:00"


def _bj_clock(results, notes):
    """A BJ chart with no clock of its own takes the Totals table's Start
    time for its interval.

    The JobMaster charts (2019 Duvernay) plot elapsed minutes and print only
    the JOB's start date in the footer; the per-interval Totals table on the
    same book prints "1/29/2025 2:33" for every interval. Joined by stage
    number, only where the chart's clock is the default.
    """
    tab = next((r for r in results if r.get("type") == "table"
                and str(r.get("source") or "").startswith("Totals")), None)
    if tab is None:
        return
    cols = list(tab.get("columns") or [])
    si = next((i for i, c in enumerate(cols) if _STAGE_COL.match(str(c))), None)
    if si is None:
        # 00575's sheet heads the column "SURFACTANT, FraCare FBS 200
        # Interval #" — a heading from the row above spilt into the cell
        si = next((i for i, c in enumerate(cols)
                   if re.search(r"\bInterval\s*#", str(c), re.I)), None)
    ti = next((i for i, c in enumerate(cols) if re.search(r"start", str(c), re.I)), None)
    if si is None or ti is None:
        return
    clocks = {}
    for row in tab.get("rows") or []:
        if max(si, ti) >= len(row):
            continue
        n = pe.stage_num(row[si])
        got = _totals_start(row[ti])
        if n < 10 ** 9 and got:
            clocks[n] = got
    if not clocks:
        return
    took = 0
    for r in results:
        if r.get("type") != "series" or not str(r.get("source") or "").startswith("BJ"):
            continue
        md = r["meta"]
        if (md.get("start_time") or "00:00:00") != "00:00:00":
            continue
        n = pe.stage_num(str(md.get("stage") or ""))
        if n in clocks:
            md["date"], md["start_time"] = clocks[n]
            md.setdefault("warnings", []).append(
                "clock: the Totals table's Start time for this interval — the "
                "chart plots elapsed minutes and prints none")
            took += 1
    if took:
        notes.append(f"{took} BJ chart(s) clocked from the Totals table's Start time "
                     f"for their interval; the charts plot elapsed minutes and print "
                     f"no clock of their own")


def _stage_from_depth(results, table, tol_m=1.5):
    """A STEP chart whose header OCR lost its "Treatment N" but kept its
    interval takes the stage number from the Daily Stage Summary row with
    that Top Depth. -> the number of charts numbered.

    00180-1021 p98: the header reads "6,837.00 m - 6,877.30 m — a 0 a I ee"
    where p100 reads "Treatment 5 6,727.00 m - 6,777.30 m"; the sheet on
    p95 prints Top Depth 6,837.0 against stage 2. The interval is the one
    thing that is printed twice, so it is the join.
    """
    if not table:
        return 0
    cols = list(table.get("columns") or [])
    si = next((i for i, c in enumerate(cols) if _STAGE_COL.match(str(c))), None)
    ti = next((i for i, c in enumerate(cols) if re.search(r"top\s*depth", str(c), re.I)), None)
    if si is None or ti is None:
        return 0
    depth = []
    for row in table.get("rows") or []:
        if max(si, ti) < len(row):
            try:
                depth.append((float(str(row[ti]).replace(",", "")), str(row[si]).strip()))
            except ValueError:
                continue
    if not depth:
        return 0
    took = 0
    for r in results:
        if r.get("type") != "series" or not str(r.get("source") or "").startswith("STEP"):
            continue
        md = r["meta"]
        if str(md.get("stage") or "").strip() or md.get("top_m") is None:
            continue
        near = min(depth, key=lambda d: abs(d[0] - md["top_m"]))
        if abs(near[0] - md["top_m"]) <= tol_m:
            md["stage"] = near[1]
            md["title"] = f"Interval {near[1]}"
            md.setdefault("warnings", []).append(
                f"stage number from the Daily Stage Summary: its Top Depth {near[0]:g} m "
                f"is this chart's interval; the chart's own header did not read")
            took += 1
    return took


def _step_stage_from_depth(doc, results, notes):
    if step_summary is None or not any(
            r.get("type") == "series" and str(r.get("source") or "").startswith("STEP")
            and not str(r["meta"].get("stage") or "").strip() and r["meta"].get("top_m") is not None
            for r in results):
        return
    try:
        table = step_summary.parse_stage_summary(doc)
    except Exception:
        return
    took = _stage_from_depth(results, table)
    if took:
        notes.append(f"{took} STEP chart(s) numbered from the Daily Stage Summary by "
                     f"their interval's Top Depth — the header's own number did not read")


def _step_clock(doc, results, notes):
    """Give a STEP chart that prints no clock the start time its own report
    files for that stage, and check the ones that do print one against it.

    THE CHARTS DISAGREE ABOUT WHAT THEY PLOT AGAINST. The 2017 Shell books
    (00196, 00199) and the 2024 ones draw a wall clock — 19:30, 19:35 … — and
    step1 now reads it. The tiled 2017 books (00183/4/5) and the vector ones
    (00180) draw "Time (min)" against an acquisition clock that restarts
    between job files and whose origin is printed NOWHERE on the page: on
    00184 it runs 615..660 for a stage the report dates 22:32, and 615 minutes
    is not 22:32 past anything the page names. Those pages have no clock to
    read, and read none.

    What every one of these books does print is the Daily Stage Summary's
    "Start Time (hh:mm)" column, one row per stage. That is the filed number —
    for 00664 it matches BCER's FRAC START TIME on all 36 stages to the minute
    — so it is the report's own answer to when the stage began, and stamping
    it beats leaving the file at midnight.

    It is not the same instant as sample 0, and the note says so. Sample 0 is
    where the plot window opens, and across the 140 stages in 00196/00199/
    00664 where the chart prints its own clock AND the sheet files one, the
    window opens within 15 minutes of the filed start on 88% of them and
    within 30 on 98% (00199 stage 12: window 19:26:12, filed 19:19; 00664
    stage 20: window 12:06:06, filed 12:10). So a chart that read its own
    clock KEEPS it — the sheet only fills a blank — and the sheet's DATE is
    taken only where the chart printed none, or where the two already agree
    about the time of day.
    """
    if step_summary is None:
        return
    step = [r for r in results
            if str(r.get("source") or "").startswith("STEP")
            and r.get("type") == "series"]
    if not step:
        return
    try:
        clocks = step_summary.stage_clock(doc)
    except Exception as e:                      # pragma: no cover - defensive
        notes.append(f"STEP stage summary unreadable, so charts keep whatever "
                     f"clock they print themselves — {e}")
        return
    if not clocks:
        return
    filled, redated, missing = 0, 0, []
    for r in step:
        md = r["meta"]
        entry = step_summary.stage_clock_for(clocks, md.get("stage"))
        ours = _hms(md.get("start_time"))
        on_clock = (md.get("start_time") or "") not in ("", "00:00:00")
        if entry is None:
            if not on_clock:
                missing.append(str(md.get("stage") or "?"))
            continue
        if on_clock:
            # The chart read its own clock; only its DATE can still be filled
            # or corrected, and the sheet is allowed to do that ONLY when the
            # two agree about the time of day. They usually do to within a few
            # minutes — but 00664 p130 is titled Interval 22 while plotting a
            # window its own footer dates 07/05 10:57:23, three minutes after
            # interval 21's and three HOURS from the 13:55 the sheet files for
            # 22. Taking the sheet's day there moved a correctly dated chart
            # onto the wrong day. A row that far from the chart is not that
            # chart's row, whatever the numbering says, so it says nothing
            # about its date either.
            day = entry.get("date")
            if not day:
                continue
            printed = _hms(entry["start"]) or 0
            want = _day_shift(day, ours or 0, printed)
            if not md.get("date"):
                md["date"] = want       # nothing printed a day; this is it
                redated += 1
                continue
            gap = abs((ours or 0) - printed)
            if min(gap, 86400 - gap) > 90 * 60:
                continue                # not this chart's row — leave its own
            if md["date"] != want:
                md["date"] = want
                redated += 1
            continue
        md["start_time"] = entry["start"]
        if entry.get("date"):
            md["date"] = entry["date"]
        filled += 1
    if filled:
        notes.append(
            f"{filled} STEP chart(s) placed on the clock from the report's "
            f"Daily Stage Summary — their time axis is elapsed minutes and "
            f"prints no start of day. That column is the stage's FILED start, "
            f"which the charts that do print a clock show opening within "
            f"about 15 minutes of it, so read these as the stage's start "
            f"time, not as the exact instant of the first sample.")
    if redated:
        notes.append(f"{redated} STEP chart(s) re-dated from the Daily Stage "
                     f"Summary — the day printed under the chart did not "
                     f"match the day the stage is filed under.")
    if missing:
        notes.append(f"stage(s) {', '.join(sorted(set(missing))[:8])} are not "
                     f"in the Daily Stage Summary, so their clock is left "
                     f"blank rather than defaulted to midnight.")


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
        # The printed time axis is what TELLS the charts apart, but it is a
        # clock, and a clock does not belong in a stage name: "Stage 10 May-31
        # 14:00" reads as a stage called after a date. The client's rule is
        # that only a printed DESCRIPTION should ever be appended — BJ's own
        # "Plug Slip" or "10.1" already arrive that way from bj1 and never
        # reach here. So the axis still decides the grouping and the order,
        # and the name it produces is a plain occurrence counter.
        order = {w: i for i, w in enumerate(wins)}      # page order = time order
        for r in grp:
            w = r["meta"].get("axis_window") or ""
            if w in tags:
                n = order[w] + 1
                r["meta"]["stage"] = stage if n == 1 else f"{stage} ({n})"
        notes.append(f"Stage {stage} is charted {len(wins)} times under one "
                     f"title with nothing printed to tell them apart — kept "
                     f"separate in chart order as "
                     + ", ".join(f'"{stage}"' if i == 0 else f'"{stage} ({i + 1})"'
                                 for i in range(len(wins)))
                     + f" (time axes: {', '.join(tags[w] for w in wins)})")


def _tile_key(page):
    """The image xrefs a tiled STEP page is built from, when it is one
    (three or more strips as wide as the page) — the identity of its plots.
    None for any other page."""
    try:
        w = float(page.rect.width or 0)
        xr = sorted(im[0] for im in page.get_images(full=True) if im[2] >= 0.3 * w)
    except Exception:
        return None
    return tuple(xr) if len(xr) >= 3 else None


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

# Which table columns hold a moment in time.
#
# This matched on "_" boundaries, so it caught the schedule parsers' snake_case
# (`start_time`, `date`) and MISSED every column a report actually titles —
# "Date (YYYY-MM-DD)", "Start Time (YYYY-MM-DD hh-mm-ss)", "Job Date". Those
# went out in whatever shape the filing printed them, while the seconds CSV
# beside them used YYYY-mm-dd HH:MM:SS.
# Matched against the name with "_" read as a space, so `start_time` and
# "Start Time" are the same column to this — "_" is a word character, so a
# plain \b would have quietly dropped every snake_case name the schedule
# parsers emit.
_DATE_COL = re.compile(r"\b(start|end|date|time|datetime)\b", re.I)
# ...but a DURATION is not a moment. "Total Pump Time (hh:mm:ss)" and "Down
# Time" hold elapsed spans, and 01:30:00 parsed as a clock would export as
# 1900-01-01 01:30:00 — a date nobody wrote.
_SPAN_COL = re.compile(r"\b(?:down|pump(?:ing)?|total|elapsed|cumulative|"
                       r"shut[- ]?in|treating|per)\b[^)]*\btime\b|"
                       r"\btime\s*(?:/|per)|"
                       r"\btime\b[^)]*\(\s*(?:min|sec|hour)",
                       re.I)
_DT_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M",
               "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
               "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M",
               # Halliburton's Treatment Time table writes the clock with
               # hyphens: "2025-08-30 03-16-07"
               "%Y-%m-%d %H-%M-%S", "%Y-%m-%d %H-%M",
               "%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%y", "%d-%b-%Y",
               "%b %d, %Y", "%d %b %Y",
               # The Frac Detail grid on a Resource Energy Solutions daily
               # completion writes the same m/d/y with HYPHENS, and the
               # WellView table built from it therefore carried "10-19-25"
               # through to the export unformatted. Month first is not an
               # assumption here: page 57 of 01340 prints "Oct 31, 2025" in
               # its own header beside a row reading "10-31-25", and 31 is
               # not a month.
               #
               # LAST in the list on purpose. _fmt_dt returns the first
               # format that parses, so this can only reach a cell that
               # nothing above it matched.
               "%m-%d-%y")


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


# What a table IS, independent of which provider printed it. The client asks
# for "the schedule" and gets a list of thirteen titles with no marker on any
# of them — Halliburton alone prints 14 tables per filing. Classifying once,
# centrally, from the title lets the Lab group them and lets a schedule export
# select them without every call site having to agree on a convention.
#
# Built from the 37 distinct titles the corpus actually produces, plus the
# schedule titles the parsers define: ifs_tables' "Pumping Schedule (design)"
# and "Stage Summary (pumped schedule)", hal1_tables' deferred "Actual Design
# (pump schedule)", and Canyon's per-substage log.
_KIND_RULES = [
    ("schedule", re.compile(r"pump(?:ed|ing)?\s+schedule|\bschedule\b|"
                            r"job design|actual design", re.I)),
    ("log", re.compile(r"\b(?:event\s+log|treatment\s+log|time\s*log|"
                       r"timetracker)\b", re.I)),
    ("summary", re.compile(r"summary|summaries|totals|treatment details|"
                           r"completion details|per-stage engineering", re.I)),
]


def table_kind(title):
    """-> 'schedule' | 'log' | 'summary' | 'other'.

    Order matters: "Stage Summary (pumped schedule)" is a SCHEDULE that has
    the word summary in it, so schedule is tested first.
    """
    t = str(title or "")
    for kind, pat in _KIND_RULES:
        if pat.search(t):
            return kind
    return "other"


_VARIANT_STAGE = re.compile(r"^(.*?)\s+(Surface|BH)$")
# the four channels a Calfrac stage is supposed to carry
_CANON4 = frozenset(("Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc"))


def _drop_chemical_only(results, notes):
    """A chart carrying no treatment channel is not a second stage.

    Liberty and BJ print each stage twice: a treatment plot, then a chemical
    plot on the very next page. Both are captioned with the same stage, so
    they arrive as two charts under one key — 01792 has 106 charts for 53
    stages, 00627 has 42 for 21, and every single key is doubled.

    Carmine, #553: "it is double plotting the stages with the 2nd one being
    the chemical, we should only display OUR TERMS."

    The rule is the same for both providers and needs no template knowledge:
    resolve each chart's channels through the alias table, and if a chart
    contributes NOT ONE of the four canonical channels while a sibling under
    the same stage does, it is the chemical sheet. It is dropped rather than
    merged, because merged it brings only channels that never export and
    never draw in Our Terms, while dragging its page into the stage's source
    list and behind the ghost overlay.

    Guarded so it can only ever remove a chart that adds nothing: if NO chart
    under a key carries a canonical channel, every one is kept — a chemicals-
    only well still comes through exactly as before.
    """
    canon = set(pe.CANON)

    def treats(r):
        for name in (r.get("data") or ()):
            c = aliases.canon(name)
            if (c or name) in canon:
                return True
        return False

    groups = {}
    for r in results:
        if r.get("type") != "series":
            continue
        groups.setdefault((r.get("source"), str((r.get("meta") or {}).get("stage"))),
                          []).append(r)
    drop_ids = set()
    for (_src, stage), g in groups.items():
        if len(g) < 2:
            continue
        keep_ids = {id(r) for r in g if treats(r)}
        if not keep_ids or len(keep_ids) == len(g):
            continue                       # nothing to choose, or nothing spare
        drop_ids |= {id(r) for r in g if id(r) not in keep_ids}
    dropped = len(drop_ids)
    if drop_ids:
        results[:] = [r for r in results if id(r) not in drop_ids]
    if dropped:
        notes.append(f"{dropped} chemical-only chart(s) set aside: each shared a "
                     f"stage with a treatment chart and carried none of the four "
                     f"channels, so it doubled the stage without adding a reading")
    return results


def _pick_variant(results, notes):
    """One chart per zone where Calfrac printed the zone twice.

    Calfrac prints each zone as a "… Surface" sheet and a "… Bottom Hole"
    sheet. Both are real and both carry Treating Pressure with DIFFERENT
    values, which is why they are kept under separate keys — merged, that
    channel ends up holding two recordings (#341). But that left the question
    of which of the two IS the stage unanswered, and both were exported.

    Carmine's rule, #550: "we should be getting the stage label from the
    surface and using the bottom if the surface only has one conc curve; if
    the surface chart has our 4 curves we use it". On 00100 the Surface sheet
    for zone 2 carries Tr Press, Slurry Rate and ONE conc — the reading he
    wants there is the Bottom Hole sheet.

    So: Surface wins when it carries all four canonical channels, otherwise
    Bottom Hole does. Only zones that printed BOTH are touched — a zone with
    one sheet has nothing to choose between and is left exactly as it was —
    and the sheet not chosen is named in the notes rather than dropped
    silently.
    """
    # Grouped by zone and then split by PAGE ORDER, because a zone can be
    # treated twice and the report prints it twice. 00886 prints zones 1..31
    # with none missing and 35 Surface sheets: zones 1, 13, 17 and 30 each
    # ran twice. Its Bottom Hole sheets print no zone number of their own at
    # all and inherit the page before them, so the sheets arrive
    # Surface(13), BH(13), Chemicals(13), ... Surface(13), BH(13).
    #
    # Keyed on kind alone, a dict kept whichever Surface and whichever BH came
    # last and dropped only those, pairing sheets from DIFFERENT treatments
    # and stranding the rest: Carmine got zone 13 as "13", "13 Surface" and
    # "13 BH" together and reported it (#617). Walking page order pairs each
    # Surface with the Bottom Hole that follows IT, which is the only pairing
    # the layout actually supports.
    groups = {}
    for r in sorted(results, key=lambda x: (x.get("page") is None,
                                            x.get("page") or 0)):
        if r.get("type") != "series" or r.get("source") != "CalFrac chart":
            continue
        m = _VARIANT_STAGE.match(str((r.get("meta") or {}).get("stage") or ""))
        if not m:
            continue
        base, kind = m.group(1), m.group(2)
        runs = groups.setdefault(base, [])
        # A Surface sheet opens a treatment. A Bottom Hole sheet joins the one
        # open, and opens its own only if it arrived first.
        if kind == "Surface" or not runs or "BH" in runs[-1]:
            runs.append({})
        runs[-1][kind] = r

    dropped = []
    for base, runs in sorted(groups.items()):
        for n, g in enumerate(runs):
            surf, bh = g.get("Surface"), g.get("BH")
            if not surf or not bh:
                continue
            # A second treatment of one zone must not be labelled the same as
            # the first: every consumer merges same-stage charts by sample
            # index (pipeline_export.build_well, the Lab's stageItems), so two
            # treatments under one key fuse into a chart belonging to neither
            # — the failure bj1's own comment describes for a re-pumped stage.
            # CalFrac prints no suffix of its own, unlike BJ's "10.1" and
            # STEP's "1.2", so one is added; stage_num reads the leading
            # integer, so it still sorts beside its zone.
            label = base if n == 0 else f"{base} ({n + 1})"
            n_surf = len(_CANON4 & set(surf.get("data") or ()))
            keep, drop = (surf, bh) if n_surf == len(_CANON4) else (bh, surf)
            keep["meta"]["stage"] = label
            # The two sheets are one zone at one time, so a date or clock
            # printed on either belongs to both — and only ONE of them prints
            # it. The Bottom Hole sheet of an MView zone carries no "March 1,
            # 2022" line, so whenever it won this choice the stage lost its
            # date on the way out: 17 of 41 charts dated on 00339, 22 of 39 on
            # 00342. Filled only where the kept sheet has nothing, so the
            # sheet we chose still speaks for itself wherever it can.
            for field in ("date", "start_time"):
                if not str(keep["meta"].get(field) or "").strip():
                    borrowed = str((drop.get("meta") or {}).get(field)
                                   or "").strip()
                    if borrowed:
                        keep["meta"][field] = borrowed
            dropped.append((label, "Surface" if drop is surf else "BH",
                            "Surface" if keep is surf else "BH", n_surf))
            # by identity — see _drop_chemical_only: == on these dicts can
            # reach a numpy `samples` array and raise
            _d = id(drop)
            results[:] = [r for r in results if id(r) != _d]
    if dropped:
        bits = ", ".join(f"{b} (kept {k})" for b, _d, k, _n in dropped)
        notes.append(f"Calfrac prints each zone twice; kept one sheet per "
                     f"treatment — Surface when it carries all four channels, "
                     f"Bottom Hole otherwise: {bits}")
    retreats = sorted(b for b in groups if len(groups[b]) > 1)
    if retreats:
        notes.append(f"zone(s) {', '.join(retreats)} were treated more than "
                     f"once and the report prints each run separately; the "
                     f"later runs are labelled \"N (2)\" so they stay their "
                     f"own charts instead of merging into the first.")
    return results


# A table's stage column: the Lab's own Stage Number term, plus the bare
# "Interval" Canyon prints, admitted only when its values are numbers.
_STAGE_COL = re.compile(r"^\s*(stage(\s*(no\.?|number|#|_number))?|zone\s*#?|interval\s*#?)\s*$", re.I)
_LABEL_COL = re.compile(r"stage\s*label|interval\s*label", re.I)
_HAS_DATE = re.compile(r"\bdate\b", re.I)
_HAS_START = re.compile(r"\bstart\b", re.I)


_INTERVAL_RE = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?[\d,]+(?:\.\d+)?)")


def _parse_interval(text):
    """'2,702.50-2,802.50 m' / '4055.65 - 4056.65 m' -> (top_m, base_m), or
    (None, None). Metres are what every template prints; feet would need a
    unit on the page and none has printed one."""
    m = _INTERVAL_RE.search(str(text or ""))
    if not m:
        return None, None
    try:
        a, b = (float(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")))
    except ValueError:
        return None, None
    return (min(a, b), max(a, b))


def _set_depth(meta, top=None, base=None):
    """Stage depth on the meta, when the page gave one: top_m <= base_m, a
    single depth as both. Never overwrites a depth already there."""
    if meta.get("top_m") is not None or meta.get("base_m") is not None:
        return
    if top is None and base is None:
        return
    if top is None:
        top = base
    if base is None:
        base = top
    meta["top_m"], meta["base_m"] = float(min(top, base)), float(max(top, base))


# "Top Depth (m)", "Bottom Depth (mKB)", CalFrac's "Interval Top (m)",
# a bare "MD (m)" — a column named for a depth, or a top / bottom in metres
_DEPTH_COL = re.compile(r"depth|\b(?:interval|perf|zone)\s*(?:top|bottom|base)\b"
                        r"|\b(?:top|bottom|base)\s*\(\s*m|\bMD\s*\(", re.I)
_TOP_COL = re.compile(r"\btop\b|\bfrom\b|\bupper\b", re.I)
_BASE_COL = re.compile(r"\bbottom\b|\bbase\b|\bto\b|\blower\b", re.I)


def _join_stage_depth(results):
    """A chart that printed no depth takes it from a table that did, by
    stage number: the BJ Totals table's "Top Depth (m)", Peloton's Top /
    Bottom Depth, the FracR sheet's depth. Only where the chart has none,
    and only where the table's stage numbers are real stage numbers.

    The well view draws each stage at its depth along the lateral; a stage
    with none is placed by order and says so, so this join is what turns a
    BJ or Halliburton book from "placed" into "measured".
    """
    depth = {}
    for r in results:
        if r.get("type") != "table":
            continue
        cols = list(r.get("columns") or [])
        si = next((i for i, c in enumerate(cols) if _STAGE_COL.match(str(c))), None)
        if si is None:
            # the same spilt heading _bj_clock allows for: "SURFACTANT,
            # FraCare FBS 200 Interval #" (00575)
            si = next((i for i, c in enumerate(cols)
                       if re.search(r"\b(?:Interval|Stage)\s*#?\s*$", str(c), re.I)
                       and len(str(c)) < 60), None)
        if si is None:
            continue
        di = [i for i, c in enumerate(cols) if _DEPTH_COL.search(str(c))]
        if not di:
            continue
        ti = next((i for i in di if _TOP_COL.search(str(cols[i]))), None)
        bi = next((i for i in di if _BASE_COL.search(str(cols[i]))), None)
        if ti is None and bi is None:
            ti = di[0]
        for row in r.get("rows") or []:
            if si >= len(row):
                continue
            n = pe.stage_num(row[si])
            if n >= 10 ** 9 or n in depth:
                continue
            vals = []
            for i in (ti, bi):
                v = None
                if i is not None and i < len(row):
                    try:
                        v = float(str(row[i]).replace(",", ""))
                    except ValueError:
                        v = None
                vals.append(v)
            if vals[0] is not None or vals[1] is not None:
                depth[n] = (vals[0], vals[1])
    if not depth:
        return
    for r in results:
        if r.get("type") != "series":
            continue
        m = r.get("meta") or {}
        n = pe.stage_num(str(m.get("stage") or ""))
        if n in depth:
            _set_depth(m, *depth[n])


def _join_stage_meta(results):
    """Every table with a stage column carries the stage's label, date and
    start time from the chart list — the three things the Lab's stage list
    shows and the table CSVs left blank on every template (Carmine,
    2026-09-14).

    Only where the table prints no column of its own for it: a sheet with
    its own Start Time keeps it and gets nothing added. Only where the charts
    sharing that stage number AGREE — STEP's surface and chemical charts of
    one stage do, CalFrac's Surface and BH sheets do, and a stage charted
    twice on two clocks (BJ 00636's "5" and "5 (2)") does not, and stays
    blank rather than guessed. The Surface/BH suffix is a chart type, not
    part of the stage's name (#546), and is dropped from the label. A chart
    without a date or with the 00:00:00 default contributes nothing, so a
    blank here still means the file did not say.
    """
    charts = {}
    for r in results:
        if r.get("type") != "series":
            continue
        m = r.get("meta") or {}
        lab = str(m.get("stage") or "").strip()
        n = pe.stage_num(lab)
        if n >= 10 ** 9:
            continue
        v = _VARIANT_STAGE.match(lab)
        if v:
            lab = v.group(1).strip()
        date = str(m.get("date") or "").strip()
        start = str(m.get("start_time") or "").strip()
        if not date:
            start = ""                                # the default, not a clock
        charts.setdefault(n, []).append((lab, date, start))
    agreed = {}
    for n, seen in charts.items():
        labs = {x[0] for x in seen}
        dates = {x[1] for x in seen if x[1]}
        starts = {x[2] for x in seen if x[2]}
        agreed[n] = (labs.pop() if len(labs) == 1 else "",
                     dates.pop() if len(dates) == 1 else "",
                     starts.pop() if len(starts) == 1 else "")
    if not agreed:
        return
    for r in results:
        if r.get("type") != "table":
            continue
        cols = list(r.get("columns") or [])
        rows = [list(x) for x in (r.get("rows") or [])]
        si = next((i for i, c in enumerate(cols) if _STAGE_COL.match(str(c))), None)
        if si is None or not rows:
            continue
        vals = [str(row[si]).strip() for row in rows if si < len(row) and str(row[si]).strip()]
        if not vals or sum(pe.stage_num(v) < 10 ** 9 for v in vals) < 0.6 * len(vals):
            continue
        add = []
        if not any(_LABEL_COL.search(str(c)) for c in cols):
            add.append(("Stage Label", 0))
        if not any(_HAS_DATE.search(str(c)) for c in cols):
            add.append(("Date", 1))
        if not any(_HAS_START.search(str(c)) for c in cols):
            add.append(("Start Time", 2))
        if not add:
            continue
        names = [a for a, _ in add]
        out_rows = []
        for row in rows:
            n = pe.stage_num(row[si]) if si < len(row) else 10 ** 9
            meta = agreed.get(n, ("", "", ""))
            extra = [meta[k] for _, k in add]
            out_rows.append(row[:si + 1] + extra + row[si + 1:])
        r["columns"] = cols[:si + 1] + names + cols[si + 1:]
        r["rows"] = out_rows
        r["stage_meta_joined"] = names


def _normalise_tables(results, filename=None):
    fallback = pe.filename_uwi(filename) if filename else ""
    for r in results:
        if r.get("type") != "table":
            continue
        r["kind"] = table_kind(r.get("title"))
        cols = list(r.get("columns") or [])
        rows = [list(x) for x in (r.get("rows") or [])]
        for i, c in enumerate(cols):
            name = str(c).replace("_", " ")
            if not _DATE_COL.search(name) or _SPAN_COL.search(name):
                continue
            for row in rows:
                if i < len(row):
                    row[i] = _fmt_dt(row[i])
        if not any(str(c).strip().lower() == "uwi" for c in cols):
            uwi = fallback or canon_uwi(r.get("uwi"))
            cols = ["UWI"] + cols
            rows = [[uwi] + row for row in rows]
        elif fallback:
            # Same rule as build_well (#517) for a table that prints its own
            # UWI column. Guarded on the column holding ONE well: a pad or
            # multi-well summary legitimately lists several, and overwriting
            # those with the file's own UWI would merge different holes.
            i = next(i for i, c in enumerate(cols)
                     if str(c).strip().lower() == "uwi")
            vals = {str(row[i]).strip() for row in rows
                    if i < len(row) and str(row[i]).strip()}
            if len(vals) <= 1:
                for row in rows:
                    if i < len(row):
                        row[i] = fallback
        r["columns"], r["rows"] = cols, rows


def _stage_log_table(doc, results, notes):
    """The operator's daily time log as a stage table — last resort only.

    daily_ops.index() has always been read for one thing: a clock to date a
    chart the vendor's own sheet failed to date. On a filing that carries NO
    vendor charts there is nothing to date, so the stage times were parsed
    and then dropped on the floor. 00654 and 00677 are 115 and 128 pages of
    Peloton daily reports holding 41 and 47 dated stage starts, and both
    exported nothing whatsoever.

    Reached only when the document produced no series and no table, so it can
    never compete with a vendor's own stage summary — where one exists this
    is the poorer reading of the same stages and should not be offered.

    One combined column rather than a date and a clock: _normalise_tables
    formats date-ish columns to the seconds DATETIME the exporter expects,
    and a bare 'HH:MM:SS' with no day in it parses as 1900-01-01.
    """
    try:
        idx = daily_ops.index(doc)
    except Exception as e:
        notes.append(f"Daily report time log unreadable — {e}")
        return
    if not idx:
        return
    title = "Stage time log (operator daily report)"
    results.append({
        "type": "table", "title": title, "well": "", "uwi": "",
        "formation": "",
        "columns": ["Stage", "Start"],
        "rows": [[str(s), f"{idx[s]['date']} {idx[s]['start']}"]
                 for s in sorted(idx)],
        "source": title})
    notes.append(
        f"{len(idx)} stage start time(s) read from the operator's daily "
        f"reports. This filing carries no vendor treatment charts, so the "
        f"daily time log is the only stage record in it.")


def _daily_ops_fill(doc, results, notes):
    """Last resort: date and clock a chart from the OPERATOR's daily report.

    Every vendor reader dates its charts from a sheet the vendor prints, and
    when that sheet is not in the document the reader has nothing. Measured
    over 60 files on both drives: SLB PRC charts are dated 43% of the time and
    CalFrac charts clocked 71%, and the failures are whole FILES rather than
    scattered stages — 00020 and 00027 are 81 charts each, every one dated and
    not one carrying a start time, because neither document contains a
    Treatment Summary grid at all and their charts plot elapsed minutes.

    The operator files a daily report whoever pumped the job, and its time log
    names the stage in the row that fracced it. So this reads across vendors
    where the vendor sheets cannot. On the three worst files it supplies 62,
    54 and 29 stages that had none.

    LAST. It never overwrites a date or a clock that something else already
    established — the chart's own axis first, then the vendor's sheet, then
    this. Where the chart prints a clock the two can be compared, which is how
    the lost-PM bug surfaced (00121: 30 of 33 agree); where the chart plots
    elapsed minutes there is nothing to check against, so the note says where
    the value came from rather than letting it pass as the chart's own.
    """
    want = [r for r in results
            if "meta" in r and (not (r["meta"].get("date") or "").strip()
                                or (r["meta"].get("start_time")
                                    or "00:00:00") == "00:00:00")]
    if not want:
        return
    try:
        idx = daily_ops.index(doc)
    except Exception as e:
        notes.append(f"daily operations report unreadable — {e}")
        return
    if not idx:
        return
    dated = clocked = 0
    for r in want:
        md = r["meta"]
        try:
            stage = int(re.sub(r"\D", "", str(md.get("stage") or "")) or 0)
        except ValueError:
            continue
        # A lettered stage is a DISTINCT treatment — "4A" and "4B" are two
        # jobs at two times — and the log is keyed by the bare number, so
        # stamping both from one row would date one of them wrongly. 00121
        # charts 28 b, 44 HRF, 44 A, 48 HRF and 48, and those are exactly the
        # stages where the log and the chart clock disagree.
        if re.search(r"[A-Za-z]", str(md.get("stage") or "")):
            continue
        entry = idx.get(stage)
        if not entry:
            continue
        if not (md.get("date") or "").strip():
            md["date"] = entry["date"]
            dated += 1
        if (md.get("start_time") or "00:00:00") == "00:00:00":
            md["start_time"] = entry["start"]
            clocked += 1
    if dated or clocked:
        notes.append(
            f"{dated} stage(s) dated and {clocked} placed on the clock from "
            f"the operator's daily report — the chart and the vendor summary "
            f"gave neither. These times are the report's, not the chart's.")


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
    # each Multiple-Zone sheet's printed "Job Date:", read alongside them
    _sheet_dates = [None]
    # the last captioned Progress page, so its uncaptioned twin can borrow its
    # zones AND its cut positions
    _last_progress = [None]
    # the Treatment Summary grid's per-zone start time and Job Date, read once
    # per document and only when a CalFrac chart actually needs it
    _zone_clocks = [None]
    # schematic/table pages that draw like charts — reported as one line, not
    # one per page: a 171-page report has dozens and they are not errors
    _not_charts = []
    _bj_unnumbered = []      # BJ chart pages whose title names no stage
    # IFS pages that name an interval and carry the chart as a BITMAP instead
    # of vector art. The reader is a vector reader, so it finds no strokes and
    # the page is skipped — which is correct, but it used to happen in total
    # silence: 00611's Interval 27 vanished with no note and no error, and the
    # only reason anyone noticed is that Carmine counts sequential stages
    # (#557). [(page, label)], reported as one line.
    _ifs_raster = []
    # STEP plots that could not be read, {reason: [pages]} — one line per
    # cause rather than one per page, the same shape as _trican_drops.
    _step_skips = {}
    # STEP tiled pages that carry the SAME images as the page before them:
    # 00180-1021 prints stages 13, 17 and 24 twice over (p108=p109,
    # p114=p115, p123=p124 by image xref), and each pair came through as two
    # charts of one stage with identical samples. {tile key: page}, [(page,
    # page it reprints)].
    _step_seen, _step_reprints = {}, []
    # the zones a scanned MView Surface page named, for the Bottom Hole page
    # behind it, which prints no caption (the same borrowing _split_progress
    # does for the vector pages)
    _scan_zones = [None]
    # Channels a Trican layout-B page traced and then had to drop. extract_
    # image_b has always built these and nothing ever read them, so a chart
    # that came back with three of its five channels said nothing about the
    # other two — #564, where both proppant concentrations were missing from
    # all 23 stages of 00583 and the report Carmine filed had no clue in it.
    # {note text: [pages]}, so 23 pages of the same cause read as one line.
    _trican_drops = {}
    # the Hal-1 EVENT LOG, read once per document and only when a raster
    # treatment plot actually needs a calendar to date itself against
    _hal_events = [None]
    # the SLB Stimulation Service Reports, same idea and same reason: the PRC
    # chart page prints no date anywhere on it (#574)
    _slb_service = [None]

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

        # An IFS filing whose labels are outlines carries no text at all, so
        # this gate — and every gate below it — was false on all 116 chart
        # pages of 00148. ifs._page_text OCRs only such a page; one with a
        # text layer is read exactly as before.
        # Matched WITHOUT case. Builds to v4.6.3 print "(IFS v4.6.3)"; v6
        # prints "(IFS V6.0.0)", and a literal lowercase test read the whole
        # v6 family as some other document — 00084 carries the marker on 238
        # pages and this gate saw none of them (Carmine, #612).
        _ifs_text = text if _IFS_MARK.search(text) else (
            ifs._page_text(page) if len(text.strip()) < 40 else text)
        if _IFS_MARK.search(_ifs_text):
            text = _ifs_text
            # "Entire Treatment" is the v4.3.1 wording; v4.6.3 titles the same
            # page "Interval 1 – Main Treatment". Requiring the older phrase
            # dropped every chart in the newer reports — 24 of 36 IFS files
            # came back "no extractable data" with no note explaining it,
            # because the skip below is silent. Carmine's alias table already
            # lists both under Hal-2's chart_headers_include.
            # The clock-label count stays: it is what rejects the table of
            # contents, which also names intervals and carries the IFS footer.
            # The interval identifier can carry a letter — a re-frac is filed
            # as "Interval 4A". Matching bare digits here did not merge those
            # charts, it DROPPED them: 00001 prints intervals 1, 2, 3, 4A, 4B,
            # 5A, 5B, 6A, 6B and 7, and only 1, 2, 3 and 7 came out — six of
            # its ten intervals produced nothing at all, silently, through the
            # same no-note skip the comment above describes.
            titled = re.search(
                r"Interval\s+(\d{1,3}[A-Za-z]?)\s*[-\u2013\u2014]\s*(?:Entire|Main)\s+"
                r"Treatment", text)
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
                                           units, labels,
                                           geom=getattr(meta, "geom", None),
                                           scales=getattr(meta, "axes", None),
                                           frames=getattr(meta, "axes_frame", None)))
                except Exception as e:
                    notes.append(f"p{pno + 1}: IFS chart failed — {e}")
            elif (titled or sect) and _has_big_image(page):
                # An IFS page that names an interval and prints no clock is
                # normally the table of contents, which lists every interval
                # title in the report and is right to be skipped — that is what
                # the clock count above is for. A page carrying a LARGE image
                # is a different animal: the chart IS there, rendered as a
                # bitmap rather than drawn. 00611 p261 is Interval 27 in three
                # 2702px images and ONE vector path, against 192 paths and
                # 32,936 items on the vector chart page beside it. No reader
                # covers that layout yet, so the interval genuinely produces
                # nothing — but it must not do so in silence, which is the same
                # defect as #564 and 00183: an honest gap and a parser failure
                # look identical when neither says anything.
                _ifs_raster.append(
                    (pno + 1,
                     f"Interval {titled.group(1)}" if titled
                     else f"section {sect[0]}"))
            continue

        if slb.detect(page):
            try:
                for meta, samples, data, units in \
                        slb.extract_page_blocks(page, sample_sec):
                    # A PRC chart carries a clock and no calendar: its own axis
                    # says where sample 0 sits, nothing on the page says which
                    # DAY. _zone_sheet_start answers that from a "Zone N
                    # Summary" sheet, and the AER Montney filings print none —
                    # 00011 has 54 Stimulation Service Reports and zero Zone
                    # Summaries, so all 52 of its intervals came through
                    # undated. Carmine, #574: "were Stimulation Service Report
                    # page exsist we should be the date there", which is what
                    # his corpus notes have said per file all along.
                    #
                    # Read once per document, and only when a chart actually
                    # arrives without a date — a filing whose zone sheets
                    # already answered pays nothing.
                    if not getattr(meta, "date", ""):
                        if _slb_service[0] is None:
                            try:
                                _slb_service[0] = slb.service_report_index(doc)
                            except Exception:
                                _slb_service[0] = {}
                        try:
                            _iv = int(str(getattr(meta, "stage", "")).strip())
                        except (TypeError, ValueError):
                            _iv = None
                        _d = _slb_service[0].get(_iv)
                        if _d:
                            meta.date = _d
                    # A Zone Summary sheet is a picture, not a vector plot, and
                    # says so through page_source so the Lab's IMAGE badge and
                    # the ghost overlay both key off it. geom places the chart
                    # region, which is what crops the tables off the top of the
                    # companion panel. All three are None on a vector page, so
                    # this is a no-op there.
                    results.append(_series(_md(meta), samples, data,
                                           slb.page_source(page), pno + 1,
                                           units,
                                           geom=getattr(meta, "geom", None),
                                           scales=getattr(meta, "axes", None),
                                           frames=getattr(meta, "axes_frame",
                                                          None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: SLB PRC chart failed — {e}")
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
                if re.search(r"\bAdditives\b", str(getattr(meta, "title", "") or "")):
                    # JobMaster's second page per zone (00575): additive
                    # ratios and the clean rate, the same footing as
                    # CalFrac's chemicals page — noted, not exported as a
                    # stage
                    notes.append(f"p{pno + 1}: BJ additives chart (zone "
                                 f"{getattr(meta, 'stage', '?')}) — additive "
                                 f"ratios, not treatment channels")
                    continue
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
                _mm = _md(meta)
                if getattr(meta, "interval", ""):
                    # the Interval Summary layout prints the stage's depths
                    # in its header, as the tiled books do
                    _set_depth(_mm, *_parse_interval(meta.interval))
                results.append(_series(_mm, samples, data,
                                       "STEP chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None),
                                       frames=getattr(meta, "axes_frame", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: STEP vector chart failed — {e}")
            continue

        sanjel_role = sanjel.page_role(page)
        if sanjel_role and sanjel_role != "treatment":
            # Sanjel's chemical/hydration/pressure-test plots use the same
            # engine as its treatment charts. Named, not silently dropped.
            notes.append(f"p{pno + 1}: Sanjel {sanjel_role} plot — not "
                         f"treatment channels")
            continue

        if sanjel_role == "treatment":
            # MUST come before Canyon: a Sanjel plot page prints "Ticket #:"
            # and legends "Main Pressure (MPa)" / "Blender Dirty Rate
            # (m3/min)", which is exactly what canyon.detect looks for. It
            # claimed every one of them and then failed on "no panel titles",
            # which is why Sanjel filings came back with no data at all.
            try:
                meta, samples, data, units = sanjel.extract_page(page, sample_sec)
                results.append(_series(_md(meta), samples, data,
                                       "Sanjel chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None),
                                       scales=getattr(meta, "axes", None),
                                       frames=getattr(meta, "axes_frame", None)))
            except Exception as e:
                notes.append(f"p{pno + 1}: Sanjel chart failed — {e}")
            continue

        if canyon.detect(page):
            try:
                meta, samples, data, units = canyon.extract_page(page)
                results.append(_series(_md(meta), samples, data,
                                       "Canyon chart", pno + 1, units,
                                       geom=getattr(meta, "geom", None)))
            except canyon.NotAStageChart as e:
                # a chart we chose not to export, not one that broke
                notes.append(f"p{pno + 1}: Canyon overview page skipped — {e}")
            except Exception as e:
                notes.append(f"p{pno + 1}: Canyon chart failed — {e}")
            continue

        if raster and hal1.detect(page):
            try:
                md, samples, chans, info = hal1.extract_page(page)
                data = {c["label"]: c["values"] for c in chans}
                units = {c["label"]: c["unit"] for c in chans}
                frames = {c["label"]: c["axis_frame"] for c in chans
                          if c.get("axis_frame")}
                deduced = {c["label"]: c["deduced"] for c in chans
                           if c.get("deduced") is not None}
                # These plots print their date under the axis and their clock
                # along it, and every one of them used to export dated
                # 2000-01-01 at 00:00:00 (#368). hal1 reads both off the
                # picture; hal1_tables makes them agree with the report's own
                # EVENT LOG before either is believed, and returns nothing
                # when they do not.
                _date = _start = None
                if hal1_tables is not None:
                    if _hal_events[0] is None:
                        try:
                            _hal_events[0] = hal1_tables.event_log_index(doc)
                        except Exception:
                            _hal_events[0] = {}
                    try:
                        _iv = int(md.get("stage"))
                    except (TypeError, ValueError):
                        _iv = None
                    _date, _start = hal1_tables.chart_datetime(
                        info.get("t0_seconds"), info.get("axis_kind"),
                        info.get("duration_s"), info.get("start_date"),
                        _hal_events[0].get(_iv))
                meta = {"title": f"Treatment interval {md.get('stage') or '?'}",
                        "uwi": md.get("uwi", ""), "stage": str(md.get("stage") or ""),
                        "date": _date or "", "start_time": _start or "00:00:00",
                        "duration_min": len(samples) / 60.0, "warnings": []}
                if data:
                    results.append(_series(meta, samples, data,
                                           "Halliburton treatment plot (raster)",
                                           pno + 1, units,
                                           geom=info.get("geom"),
                                           frames=frames,
                                           deduced=deduced))
            except Exception as e:
                notes.append(f"p{pno + 1}: Halliburton plot failed — {e}")
            continue

        if raster and tcharts.detect(page):
            # Trican POST-FRAC SUMMARY charts. Same documents trican2 reads
            # for STAGE INFORMATION tables, which stay on the doc-level pass
            # below: the tables and the curves are different pages.
            try:
                md, samples, chans, info = tcharts.extract_page(page,
                                                                sample_sec)
                data = {c["label"]: c["values"] for c in chans}
                units = {c["label"]: c["unit"] for c in chans}
                frames = {c["label"]: c["axis_frame"] for c in chans
                          if c.get("axis_frame")}
                deduced = {c["label"]: c["deduced"] for c in chans
                           if c.get("deduced") is not None}
                if data:
                    stage = md.get("stage")
                    title = ("Whole job (continuous)" if md.get("continuous")
                             else f"Stage {stage or '?'}")
                    meta = {"title": title, "uwi": md.get("uwi", ""),
                            "stage": "" if md.get("continuous")
                            else str(stage or ""),
                            "date": "", "start_time": "00:00:00",
                            "duration_min": len(samples) / 60.0,
                            "warnings": []}
                    if md.get("continuous"):
                        meta["continuous"] = True
                    _set_depth(meta, md.get("top_m"), md.get("base_m"))
                    clk = info.get("clock_s")
                    if clk is not None:
                        # The chart's own "Clock Time (hour:min)" axis, a
                        # 24-hour clock printed above the frame, quoted to
                        # the minute it is printed at. The STAGE INFORMATION
                        # table becomes the date and a second opinion —
                        # _trican_clock. See trican_charts.clock_axis.
                        cs = int(round(clk / 60.0)) * 60 % 86400
                        meta["start_time"] = f"{cs // 3600:02d}:{cs % 3600 // 60:02d}:00"
                        meta["clock_chart"] = True
                        na, nb = info.get("clock_labels") or (0, 0)
                        meta["warnings"].append(
                            "clock: read from the chart's own Clock Time axis "
                            f"({na} of {nb} labels agree)")
                    results.append(_series(
                        meta, samples, data, "Trican treatment chart (raster)",
                        pno + 1, units, geom=info.get("geom"), frames=frames,
                        deduced=deduced))
            except Exception as e:
                notes.append(f"p{pno + 1}: Trican chart failed — {e}")
            continue

        if raster and tcharts.detect_b(page):
            # Trican "Stage # N" reports (2024/2025). Different render from
            # the POST-FRAC SUMMARY charts above: three value axes, clock
            # time, legend under the plot.
            try:
                md, samples, chans, info = tcharts.extract_page_b(page,
                                                                  sample_sec)
                # Only an unreadable axis is a DROP. The reader's other
                # notes — a curve drawn over part of the width, the
                # concentration axis checked against the printed maximum,
                # a window trimmed to the printed start — were all being
                # filed here too and came out on the file as "channel
                # dropped … the axis could not be read", forty lines of it
                # on 00910 (#648). They belong to the stage.
                _drops, _stage_notes = _route_b_notes(info.get("notes") or ())
                for _n in _drops:
                    _trican_drops.setdefault(str(_n), []).append(pno + 1)
                data = {c["label"]: c["values"] for c in chans}
                units = {c["label"]: c["unit"] for c in chans}
                frames = {c["label"]: c["axis_frame"] for c in chans
                          if c.get("axis_frame")}
                deduced = {c["label"]: c["deduced"] for c in chans
                           if c.get("deduced") is not None}
                if data:
                    stage = md.get("stage")
                    # The page prints "Interval Date 02/26/25(m/d/y)" and
                    # "Start Time 05:01(hh:mm)" in plain text beside the
                    # chart, and this read neither — every stage of every
                    # layout-B filing came out "no date 00:00:00" while the
                    # answer sat two inches away on the same page (Carmine,
                    # 2026-09-13). Still blank when the page does not say,
                    # rather than invented.
                    meta = {"title": f"Stage {stage or '?'}",
                            "uwi": md.get("uwi", ""), "stage": str(stage or ""),
                            "date": md.get("date") or "",
                            "start_time": md.get("start_time") or "00:00:00",
                            "duration_min": len(samples) / 60.0,
                            "warnings": list(_stage_notes)}
                    _set_depth(meta, md.get("depth_m"), md.get("depth_m"))
                    if md.get("clock_chart"):
                        # sample 0 is on the chart's own clock axis; the
                        # printed Start Time is the stage's and is kept
                        # beside it — see trican_charts._clock_from_axis
                        meta["clock_chart"] = True
                        meta["printed_start"] = md.get("printed_start", "")
                    results.append(_series(
                        meta, samples, data, "Trican treatment chart (raster)",
                        pno + 1, units, geom=info.get("geom"), frames=frames,
                        deduced=deduced))
            except Exception as e:
                notes.append(f"p{pno + 1}: Trican chart failed — {e}")
            continue

        if raster and step1.detect(page):
            _tk = _tile_key(page)
            if _tk and _tk in _step_seen:
                _step_reprints.append((pno + 1, _step_seen[_tk]))
                continue
            if _tk:
                _step_seen[_tk] = pno + 1
            try:
                md, charts = step1.extract_page(page, sample_sec)
                # A plot step1 could not read is one the report HAS and we do
                # not. 00344 loses its SURFACE chart — the one with pressure,
                # rate and both concentrations on it — on all 32 of its chart
                # pages, and said nothing whatever: the page still produced a
                # result, so it never looked like a failure (#585).
                for _s in (md.get("skipped") or ()):
                    _step_skips.setdefault(str(_s), []).append(pno + 1)
                if md.get("kind") == "main":
                    for tag, samples, chans, info in charts:
                        data = {c["label"]: c["values"] for c in chans}
                        units = {c["label"]: c["unit"] for c in chans}
                        frames = {c["label"]: c["axis_frame"] for c in chans
                                  if c.get("axis_frame")}
                        deduced = {c["label"]: c["deduced"] for c in chans
                                   if c.get("deduced") is not None}
                        if not data:
                            continue
                        kind = "surface" if tag == "t" else "chemical"
                        # The scanned STEP layouts carry no well, no date and
                        # a time axis in elapsed minutes, so those stay blank.
                        # The 2024 layout prints all three, and step1 fills
                        # them in — clock_start is the plot frame's left edge,
                        # which is where sample 0 sits.
                        # The date the CHART prints under itself beats the
                        # page's: a page carries one Date for a stage that can
                        # straddle midnight, and the two charts on it can land
                        # on different days. Without a date the Lab's clock
                        # axis stays off and the CSV dates from 2000-01-01,
                        # so a start time alone only half-answers this.
                        meta = {"title": f"Interval {md.get('stage') or '?'} "
                                f"({kind})", "uwi": md.get("uwi") or "",
                                "stage": str(md.get("stage") or ""),
                                "date": (info.get("clock_date")
                                         or md.get("date") or ""),
                                "start_time": info.get("clock_start")
                                or "00:00:00",
                                "duration_min": len(samples) / 60.0,
                                "warnings": list(info.get("notes") or [])}
                        _set_depth(meta, *_parse_interval(md.get("interval")))
                        # STEP reported no `scales` at all, so every STEP
                        # chart arrived with an empty axis map — and the
                        # peak-outside-axis check, the one diagnostic that
                        # cracked both the IFS and the Hal-1 clusters, cannot
                        # fire without one. An additive channel reading 1,244
                        # kg/m3 went to the client instead of to a scan.
                        # step1 fits each axis and snaps it to round bounds,
                        # so axis_frame IS the axis these values were read
                        # against — report it as both.
                        results.append(_series(
                            meta, samples, data,
                            f"STEP {kind} chart (raster)", pno + 1, units,
                            geom=info.get("geom"), scales=frames,
                            frames=frames,
                            deduced=deduced))
            except Exception as e:
                notes.append(f"p{pno + 1}: STEP chart failed — {e}")
            continue

        if raster and cscan.detect(page):
            try:
                meta, samples, data, units, info = cscan.extract_page(page, sample_sec)
            except Exception as e:
                notes.append(f"p{pno + 1}: scanned CalFrac overview failed — {e}")
                continue
            if meta.get("zones"):
                _scan_zones[0] = (meta["zones"], pno + 1)
            elif _scan_zones[0] and _scan_zones[0][1] == pno:
                # the Bottom Hole page right behind a captioned Surface page
                meta["zones"] = _scan_zones[0][0]
                meta["stage"] = f"{meta['zones']}{meta.get('mv', '')}"
                meta["title"] = f"{meta['zones']}{meta.get('mv', '')} (scanned)"
                meta["multi_zone"] = True
            results.append(_series(meta, samples, data, "CalFrac overview (scanned)",
                                   pno + 1, units, scales=info.get("frames"),
                                   frames=info.get("frames")))
            continue

        if fc.page_kind(page) == "vector":
            if not cprog.is_chart_page(page):
                untitled = bj1.unnumbered_title(page)
                if untitled:
                    _bj_unnumbered.append((pno + 1, untitled))
                else:
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
            # MView prints each zone TWICE, as consecutive pages titled
            # "… Surface" and "… Bottom Hole", and they are different charts:
            # Surface carries Tubing Pressure and Blender Slurry Rate, Bottom
            # Hole carries Bottom Hole Pressure, Combined Rate @ Formation and
            # a second Master Conc. Both are wanted. But they share a zone
            # number and BOTH carry Treating Pressure, so under one key they
            # merge and that channel ends up with two different sets of values
            # — the collision that put Canyon's overview plot on top of a real
            # stage. Tag the key so they stay apart and say which is which.
            _variant = _mview_variant(page)
            if data and cprog.detect(page):
                # a "Progress" page: several zones on one plot, no stage named
                if _zone_times[0] is None:
                    _zone_times[0], _sheet_dates[0] = \
                        cprog.sheets_for_document(doc)
                if _zone_clocks[0] is None:
                    _zone_clocks[0] = calfrac_summary.zone_clock(doc)
                for part in _split_progress(page, meta, samples, data,
                                            cprog.times_before(_zone_times[0], pno),
                                            sample_sec, notes, pno, _last_progress,
                                            _zone_clocks[0], _zone_times[0],
                                            _sheet_dates[0]):
                    pmeta, psamples, pdata, pgeom = part
                    # Recorded whether or not this page names a zone. MView's
                    # Bottom Hole page prints no caption, so its stage is
                    # blank here and the tag would be dropped on the floor —
                    # and it is the one page that most needs it, because the
                    # fill-down below is about to hand it its neighbour's
                    # zone number.
                    pmeta["mv"] = _variant or ""
                    if _variant and pmeta.get("stage"):
                        pmeta["stage"] = f"{pmeta['stage']}{_variant}"
                    results.append(_series(pmeta, psamples, pdata,
                                           "CalFrac chart", pno + 1,
                                           geom=pgeom, scales=scales))
                continue
            _mm = _md(meta)
            _mm["mv"] = _variant or ""          # same reason as above
            if _variant and _mm.get("stage"):
                _mm["stage"] = f"{_mm['stage']}{_variant}"
            results.append(_series(_mm, samples, data,
                                   "CalFrac chart", pno + 1,
                                   geom=geom, scales=scales))

    # CalFrac/MView 2013-vintage: a stage's channels are split across several
    # consecutive chart pages, only the FIRST of which carries the stage
    # number (rate+pressure numbered; the concentration pages left blank).
    # Fill the stage number down onto those blank pages so build_well merges
    # the four channels into one stage, and drop the empty whole-job overview
    # pages (no curves) that would otherwise become phantom stages.
    for _msg, _pages in sorted(_trican_drops.items()):
        notes.append(
            f"{_msg} — channel dropped on {len(_pages)} chart(s) "
            f"(p{', p'.join(str(x) for x in _pages[:8])}"
            f"{', …' if len(_pages) > 8 else ''}). The curve was traced; it is "
            f"the axis that could not be read, so there is nothing to scale it "
            f"against and it is left out rather than guessed at.")
    if _step_reprints:
        notes.append(
            f"{len(_step_reprints)} STEP page(s) reprint the page before them — "
            f"the same images, so the same plots — and are read once: "
            + ", ".join(f"p{a} = p{b}" for a, b in _step_reprints[:8])
            + (", …" if len(_step_reprints) > 8 else ""))
    for _msg, _pages in sorted(_step_skips.items()):
        notes.append(
            f"{_msg} — on {len(_pages)} page(s) "
            f"(p{', p'.join(str(x) for x in _pages[:8])}"
            f"{', …' if len(_pages) > 8 else ''}). That plot's channels are "
            f"missing from this file; the other plot on the page, if any, "
            f"came through.")
    if _ifs_raster:
        notes.append(
            f"{len(_ifs_raster)} interval chart(s) drawn as a bitmap "
            f"instead of vector art, so nothing was extracted from them: "
            f"{', '.join(f'{lbl} (p{pg})' for pg, lbl in _ifs_raster[:8])}"
            f"{', …' if len(_ifs_raster) > 8 else ''}. The chart is in the "
            f"PDF and can be read by eye; it is this reader that cannot, "
            f"because it looks for stroked curves and finds a picture.")
    if _bj_unnumbered:
        notes.append(f"{len(_bj_unnumbered)} BJ chart page(s) titled without a "
                     f"stage number, not read as a stage: "
                     + "; ".join(f"p{pg} \"{t.split(' - ', 1)[-1][:40]}\""
                                 for pg, t in _bj_unnumbered[:6])
                     + (", …" if len(_bj_unnumbered) > 6 else ""))
    if _not_charts:
        notes.append(f"{len(_not_charts)} page(s) skipped as schematics or "
                     f"tables that draw like charts (p"
                     f"{', p'.join(str(x) for x in _not_charts[:8])}"
                     f"{', …' if len(_not_charts) > 8 else ''})")

    last_stage, keep = None, []
    for r in results:
        if r.get("source") != "CalFrac chart":
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
            # The ZONE carries down; the sheet type does not.
            #
            # last_stage is the whole key, "1 Surface" and all. Copying it
            # verbatim was harmless only while these pages had no zone to
            # inherit — 00525 heads its charts "102/06-21 - Zone #1" and the
            # caption reader wanted whitespace, so every page came out blank
            # and nothing was ever filled down.
            #
            # With the zones reading (#579) it mattered at once: MView pairs
            # each zone as a captioned "… Surface" page and an uncaptioned
            # "… Bottom Hole" one, so all 50 zones of 00525 became 100 charts
            # under 50 keys, each pair merged. Both sheets carry Treating
            # Pressure, and that channel would then hold two recordings —
            # exactly the collision _mview_variant was added to prevent.
            #
            # Stripped, then the page's OWN tag goes back on: the partner
            # of "1 Surface" is "1 BH", not "1 Surface" and not a bare "1".
            # A page with no tag of its own — the 2013-vintage concentration
            # continuation this fill-down was written for — keeps the bare
            # zone, exactly as it did before.
            _own = r["meta"].get("mv") or ""
            if _own:
                r["meta"]["stage"] = (_VARIANT_STAGE.sub(r"\1", str(last_stage))
                                      + _own)
            else:
                # No tag of its own: the 2013-vintage concentration
                # continuation this fill-down was written for. It takes the
                # previous key WHOLE, tag included, exactly as it always has —
                # it is the same sheet continued, so it has to land on the same
                # key or the four channels never merge.
                r["meta"]["stage"] = last_stage
        keep.append(r)
    results[:] = keep

    # A CalFrac chart of ONE zone plots elapsed minutes with no clock printed
    # anywhere on it, so every such stage exported 00:00:00 — 932 pages across
    # 39 of the 120 files in the CalFrac corpus — and stages sharing a day
    # collapsed onto identical date ranges. The zone's real start, and the day
    # it ran, are printed in the Treatment Summary grid; it supplies one for
    # 931 of those 932. Runs after the fill-down above so a blank concentration
    # page has its stage number to look itself up by.
    #
    # A zone the grid does not name is left BLANK rather than defaulted: this
    # is exactly where a wrong clock is worse than no clock. Documents with no
    # grid at all are left alone — there is nothing to say about them.
    if any(r.get("source") == "CalFrac chart" for r in results):
        if _zone_clocks[0] is None:
            _zone_clocks[0] = calfrac_summary.zone_clock(doc)
        clocks = _zone_clocks[0]
        if clocks:
            restamped, blanked = 0, []
            for r in results:
                md = r.get("meta", {})
                if r.get("source") != "CalFrac chart" or \
                        md.get("zone_span") is not None or \
                        md.get("multi_zone"):
                    continue        # a split zone is already on the clock
                if (md.get("start_time") or "") not in ("", "00:00:00"):
                    continue        # the chart printed its own start
                entry = calfrac_summary.zone_clock_for(clocks, md.get("stage"))
                if not entry:
                    md["start_time"] = ""
                    if md.get("stage"):
                        blanked.append(str(md["stage"]))
                    continue
                md["start_time"] = entry["start"]
                if not md.get("date") and entry.get("date"):
                    md["date"] = entry["date"]
                restamped += 1
            if restamped:
                notes.append(f"{restamped} stage(s) placed on the clock from "
                             f"the Treatment Summary grid — the charts "
                             f"themselves print no start time.")
            if blanked:
                notes.append(f"stage(s) {', '.join(sorted(set(blanked))[:8])} "
                             f"have no start time in the Treatment Summary "
                             f"grid, so their clock is left blank rather than "
                             f"defaulted to midnight.")

        _calfrac_days(results, notes)

    _step_stage_from_depth(doc, results, notes)
    _step_clock(doc, results, notes)
    _trican_clock(doc, results, notes)

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

    # a BJ stage charted twice under one title -> one block per printed
    # time axis, instead of the two fusing into a block that matches neither
    _split_bj_windows(results, notes)

    # a Canyon chart page dates itself from the job, not from the interval
    _canyon_dates(doc, results, notes)

    # a Trican CONTINUOUS chart re-plots the stage charts end to end
    _trican_continuous(results, notes)
    # consecutive charts that print the same minutes twice
    _hand_over_tails(results, notes)

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
        # columns_for, not a filter over COLUMNS: the chemical and proppant
        # columns are named by the job's own products and cannot be in a
        # fixed list, so the reader is asked what these rows actually carry.
        cols = trican2.columns_for(trows)
        results.append({
            "type": "table",
            "title": (th.get("well") or "well") + " — per-stage engineering data (Trican)",
            "well": th.get("well", ""), "uwi": th.get("uwi", ""),
            "formation": "", "columns": cols,
            "rows": [[r.get(c, "") for c in cols] for r in trows],
            "source": "Trican stage report (stages numbered by document order)"})
        notes.append(f"{len(trows)} stage row(s) parsed from Trican stage reports.")

    # --- Trican 'Post-Fracturing Report' — the 2024/25 book (layout B) ---
    #
    # A different report entirely: a cover, a consolidated Stage Summary, a
    # Chemical Summary and one label/value page per stage. trican2.detect
    # needs "STAGE INFORMATION" and never fires on it, so these files yielded
    # no table at all — 66 to 88 stages each, printed and unread.
    #
    # The reader for it was written and never wired in. Verified here against
    # the report's OWN printed stage count on four files: 66/66, 85/85, 88/88,
    # 88/88, 327 rows.
    #
    # It runs whatever layout A found. The two layouts do not co-occur — one
    # is the 2015-16 deliverable and the other the 2024/25 one — so a file
    # producing rows from both is a signal worth seeing rather than a conflict
    # to suppress.
    try:
        bh, brows = trican_b.parse_document(doc)
    except Exception as e:
        bh, brows = {}, []
        notes.append(f"Trican post-frac report unreadable — {e}")
    if len(brows) >= 2:
        bcols = [c for c in trican_b.COLUMNS if any(c in r for r in brows)]
        results.append({
            "type": "table",
            "title": (bh.get("well") or "well") + " — per-stage engineering data (Trican)",
            "well": bh.get("well", ""), "uwi": bh.get("uwi", ""),
            # this book prints the formation on its cover, and the reader
            # already returns it — layout A has nowhere to read one from,
            # which is why the field above is empty rather than this one
            "formation": bh.get("formation", ""), "columns": bcols,
            "rows": [[r.get(c, "") for c in bcols]
                     for r in sorted(brows, key=lambda r: r.get("stage") or 0)],
            "source": "Trican post-frac report"})
        notes.append(f"{len(brows)} stage row(s) parsed from the Trican "
                     f"post-fracturing report.")

    # --- Schlumberger Zone / Interval Summary sheets ---
    #
    # Gated on slb_tables' OWN detector, not on whether this document produced
    # SLB charts. Gating tables on charts is why 01155's 22 clean rows emitted
    # nothing, and it bites here specifically: the sheets are text on every
    # page measured while the PRC plots beside them are pictures, so the two
    # succeed and fail independently.
    try:
        srecs = slb_tables.parse_document(doc)
    except Exception as e:
        srecs, _ = [], notes.append(f"SLB summary sheets unreadable — {e}")
    # ONLY the FLUID and PROPPANT blocks are emitted here. The scalar fields
    # of these sheets are already read, and better named, by
    # slb.parse_zone_table and slb.parse_interval_summaries — a parallel
    # parser for them would be two sources of one truth. What those two do NOT
    # read is the per-stage fluid breakdown and the per-proppant-type
    # breakdown printed lower down the same sheet, which is what this adds.
    for kind, label in (("zone", "Zone"), ("interval", "Interval")):
        group = [r for r in srecs if r["kind"] == kind]
        if not group:
            continue
        for block in ("FLUID", "PROPPANT"):
            cols, rows = [], []
            for r in group:
                tab = r["tables"].get(block)
                if not tab:
                    continue
                for c in tab["columns"]:
                    if c and c not in cols:
                        cols.append(c)
                for row in tab["rows"]:
                    rows.append((r["number"], dict(zip(tab["columns"], row))))
            if not rows:
                continue
            results.append({
                "type": "table",
                "title": f"{block.title()} by {label.lower()} (Schlumberger)",
                "well": "", "uwi": "", "formation": "",
                "columns": [label] + cols,
                "rows": [[n] + [d.get(c, "") for c in cols] for n, d in rows],
                "source": f"SLB {label} Summary sheets — {block} block"})
    if srecs:
        notes.append(f"{len(srecs)} Schlumberger summary sheet(s) read "
                     f"({sum(1 for r in srecs if r['kind'] == 'zone')} zone, "
                     f"{sum(1 for r in srecs if r['kind'] == 'interval')} "
                     f"interval).")

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

    # Gate on BJ's OWN Totals page as well as on the chart source: the 2025
    # Ovintiv/BJ books (#647) print the per-interval table and no chart at
    # all, and came back empty with 22-66 rows sitting on the last page.
    _summary(bj_summary, "BJ chart" in chart_srcs
             or bj_summary.detect_document(doc),
             "Totals — per-interval frac summary",
             lambda d: _bj_totals(d))
    # Gate on Liberty's OWN pages as well as on the chart source, for exactly
    # the reason the Calfrac note below gives. Carmine ran 299 Liberty files
    # and got the Summary view on 10: charts read on 172, and the summary was
    # unreachable on the other 127 no matter what those files printed.
    _summary(liberty_summary,
             "Liberty chart" in chart_srcs
             or liberty_summary.detect_document(doc),
             "Stimulation Summary", liberty_summary.parse_stimulation)
    # Calfrac printed three different summary layouts across the corpus and
    # only the newest one was ever read, so most Calfrac wells came back with
    # charts and no engineering table at all. Gate on Calfrac's OWN pages as
    # well as on the chart source: the older sheets carry the summary and the
    # plot side by side, and a filing prints its tables whether or not we can
    # read its plots. Keeping the chart test in the OR leaves the documents
    # that already produced a table exactly as they were.
    _calfrac_legacy_doc = calfrac_legacy is not None and calfrac_legacy.detect(doc)
    _summary(calfrac_summary,
             "CalFrac chart" in chart_srcs or _calfrac_legacy_doc
             or calfrac_summary.detect(doc),
             "Treatment Summary", calfrac_summary.parse_treatment_summary)

    # SLB prints two tables worth having. The zone grid is the only place in
    # the corpus carrying minimum slurry rate, ball size and interval length
    # per stage. Both return uwi "" on purpose so _normalise_tables fills it
    # from the filename — ~39 of these files print a UWI belonging to a
    # NEIGHBOURING well, and on some pads two reports carry each other's.
    _slb_doc = slb.detect_document(doc)
    _summary(slb, _slb_doc,
             "Per-zone treatment summary", slb.parse_zone_table)
    if _slb_doc:
        try:
            tab = slb.parse_interval_summaries(doc)
        except Exception as e:
            tab = None
            notes.append(f"Interval summaries parse failed — {e}")
        if tab and tab.get("rows"):
            results.append({"type": "table", "title": "Interval summaries",
                            "well": "", "uwi": "", "formation": "",
                            "columns": tab["columns"], "rows": tab["rows"],
                            "source": "Interval summaries"})

    # --- Table parsers built and verified earlier but never wired in ---
    #
    # Each is gated on its OWN detector rather than on a chart source. The
    # older summaries above key off `chart_srcs`, and that is precisely why
    # 01155's Totals page — which parses cleanly into 22 interval rows —
    # produced nothing at all: its charts were not recognised, so its tables
    # were never asked for. A filing that prints a table still prints it
    # whether or not we can read its plots.
    def _table(title, tab, well="", uwi=""):
        if tab and tab.get("rows"):
            results.append({"type": "table", "title": title, "well": well,
                            "uwi": uwi, "formation": "",
                            "columns": tab["columns"], "rows": tab["rows"],
                            "source": title})

    def _tables_from(mod, name, jobs, gate=None):
        """gate() -> bool decides whether this document is even a candidate;
        jobs is [(title, callable)] evaluated lazily so a document that is not
        this provider's never pays for the parse."""
        try:
            if gate is not None and not gate():
                return
            try:
                groups = mod.find_summary_pages(doc)
            except Exception:
                groups = []
            if groups:
                results.append({"type": "summary", "groups": groups,
                                "source": name})
            for title, fn in jobs:
                try:
                    _table(title, fn())
                except Exception as e:
                    notes.append(f"{title} parse failed — {e}")
        except Exception as e:                  # pragma: no cover - defensive
            notes.append(f"{name} tables failed — {e}")

    # Per-interval sheets: one page per stage, the roll-up as text above an
    # embedded RASTER chart. 00900-00905 reported "no page in it draws a
    # plotted curve", which was true of the charts and said nothing about the
    # 323 stages of text sitting above them.
    _tables_from(interval_sheet, "Interval summary sheets",
                 [("Interval summary (per-stage sheets)",
                   lambda: interval_sheet.parse_document(doc))],
                 gate=lambda: interval_sheet.detect_document(doc))

    _tables_from(step_summary, "STEP stage summary",
                 [("Daily Stage Summary",
                   lambda: step_summary.parse_stage_summary(doc))],
                 gate=lambda: step_summary is not None and step_summary.detect(doc))

    _tables_from(canyon_tables, "Canyon tables", [
        ("Treatment Interval Summary",
         lambda: canyon_tables.parse_interval_summary(doc)),
        ("Treatment Summary (Canyon)",
         lambda: canyon_tables.parse_treatment_summary(doc)),
        # one row per SUBSTAGE at printed precision — the same quantities the
        # curves trace, so it doubles as ground truth for the chart side
        ("Treatment Log",
         lambda: canyon_tables.parse_treatment_log(doc)),
    ], gate=lambda: canyon_tables is not None
                 and bool(canyon_tables.find_summary_pages(doc)))

    # Calfrac's two pre-2024 layouts, one row per zone — the same grain as the
    # modern grid parsed above. Only one of the two fires on a given well:
    # they are alternative vintages of the same sheet, not companions.
    _tables_from(calfrac_legacy, "Calfrac legacy summary", [
        ("Multiple Zone Frac Treatment Summary",
         lambda: calfrac_legacy.parse_multizone(doc)),
        ("Treatment Summary (per-stage sheets)",
         lambda: calfrac_legacy.parse_datasheets(doc)),
    ], gate=lambda: _calfrac_legacy_doc)

    _tables_from(ifs_tables, "IFS stage summary", [
        ("Stage Summary", lambda: ifs_tables.parse_stage_summary(doc)),
        ("Treatment Summary (IFS)",
         lambda: ifs_tables.parse_treatment_summary(doc)),
    ], gate=lambda: ifs_tables is not None and ifs_tables.detect(doc))

    if hal1_tables is not None:
        def _hal1_sections():
            # parse_sections returns one (key, title, table) per named section
            for sec in hal1_tables.parse_sections(doc):
                tab = next((x for x in sec if isinstance(x, dict)), None)
                title = next((x for x in sec[1:] if isinstance(x, str)), None)
                _table(f"{title or 'Section'} (Hal-1)", tab)
        _tables_from(hal1_tables, "Hal-1 stimulation report", [
            ("Event log (Hal-1)",
             lambda: hal1_tables.parse_event_logs(doc)),
        ], gate=lambda: hal1_tables.detect(doc))
        try:
            if hal1_tables.detect(doc):
                _hal1_sections()
        except Exception as e:
            notes.append(f"Hal-1 sections parse failed — {e}")

    if sanjel_tables is not None:
        try:
            for tab in sanjel_tables.parse_all(doc) or []:
                # uwi is left empty on purpose — the printed banner names a
                # DIFFERENT well on the 2015 vintage, so _normalise_tables
                # fills it from the filename (see sanjel.py)
                _table(tab.get("title") or "Sanjel table", tab)
        except Exception as e:
            notes.append(f"Sanjel tables parse failed — {e}")

    # BJ's "Fracturing-Acidizing Treatment" sheets: a whole filing of these and
    # no charts at all reported "No extractable data" for weeks (#332/#360/#361
    # on 00058, 218 pages). Gated on its OWN pages, not on a chart source —
    # that is the entire point, these documents plot nothing.
    try:
        if bj_fracturing.detect(doc):
            _bjf = bj_fracturing.parse_document(doc)
            if _bjf.get("schedule"):
                _table("Pumped schedule (BJ Fracturing-Acidizing)",
                       _bjf["schedule"])
            if _bjf.get("summary"):
                _table("Per-frac summary (BJ Fracturing-Acidizing)",
                       _bjf["summary"])
    except Exception as e:
        notes.append(f"BJ Fracturing-Acidizing tables failed — {e}")

    # Asked of the results a client can actually USE, not of the list.
    # A "summary" result is a page-viewing aid — find_summary_pages found
    # pages worth showing — and it carries no rows and no samples: nothing
    # exports from it and nothing draws. One of them was enough to make this
    # list non-empty and silence the explanation below, so 00654, 00677,
    # 00698 and 00700 each came back with no data AND no note saying why,
    # which is the one outcome _why_nothing exists to prevent.
    if not any(r.get("type") in ("series", "table") for r in results):
        _stage_log_table(doc, results, notes)
    if not any(r.get("type") in ("series", "table") for r in results):
        notes.append(_why_nothing(doc, npages, raster))
    _pick_variant(results, notes)
    _drop_chemical_only(results, notes)
    # AFTER the variant pick, and that placement is the whole of it. Before it
    # a CalFrac stage is still tagged with its MView sheet — "1 Surface",
    # "1 BH" — and the guard below, which exists to keep a re-frac's "4A" and
    # "4B" from sharing one log row, threw away all 162 of them because the
    # tag contains letters. Surface and BH are two VIEWS of one stage at one
    # time, not two treatments; _pick_variant collapses them to a bare "1"
    # and only then is the stage in the form the daily report names.
    _daily_ops_fill(doc, results, notes)
    # after the summary tables are on the results: the BJ Totals table is
    # what clocks a JobMaster chart
    _bj_clock(results, notes)
    _normalise_tables(results, filename)
    _join_stage_depth(results)
    _join_stage_meta(results)
    return results, notes
