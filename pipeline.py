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


def _mview_variant(page):
    """-> " Surface" / " BH" / "" from an MView page's own title line.

    Read through ocr_labels, so a Type3 filing gets the tag too. Without it
    the Surface and Bottom Hole pages of a zone share one key and merge, and
    both carry Treating Pressure — which is the collision this tag exists to
    prevent.
    """
    try:
        head = (ocr_labels.page_text(page).strip().splitlines() or [""])[0]
    except Exception:
        return ""
    if re.search(r"\bbottom\s*hole\b", head, re.I):
        return " BH"
    if re.search(r"\bsurface\b", head, re.I):
        return " Surface"
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
        return (base + " — this file draws no curves and carries no text layer "
                "at all: every page is a picture. Reading it needs OCR, and it "
                "may be a daily report that holds no treatment charts to begin "
                "with.")
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
    dated = clocked = 0
    for r in tri:
        md = r["meta"]
        m = re.match(r"\d+", str(md.get("stage")).strip())
        if not m:
            continue
        entry = clocks.get(int(m.group(0)))
        if not entry:
            continue
        if not md.get("date") and entry["date"]:
            md["date"] = entry["date"]
            dated += 1
        if (md.get("start_time") or "00:00:00") == "00:00:00" \
                and entry["start"] != "00:00:00":
            md["start_time"] = entry["start"]
            clocked += 1
    if dated or clocked:
        notes.append(f"{max(dated, clocked)} Trican chart(s) dated and clocked "
                     f"from the STAGE INFORMATION page that follows each one")


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
               "%b %d, %Y", "%d %b %Y")


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
    groups = {}
    for r in results:
        if r.get("type") != "series" or r.get("source") != "CalFrac chart":
            continue
        m = _VARIANT_STAGE.match(str((r.get("meta") or {}).get("stage") or ""))
        if m:
            groups.setdefault(m.group(1), {})[m.group(2)] = r

    dropped = []
    for base, g in sorted(groups.items()):
        surf, bh = g.get("Surface"), g.get("BH")
        if not surf or not bh:
            continue
        n_surf = len(_CANON4 & set(surf.get("data") or ()))
        keep, drop = (surf, bh) if n_surf == len(_CANON4) else (bh, surf)
        keep["meta"]["stage"] = base
        dropped.append((base, "Surface" if drop is surf else "BH",
                        "Surface" if keep is surf else "BH", n_surf))
        # by identity — see _drop_chemical_only: == on these dicts can reach
        # a numpy `samples` array and raise
        _d = id(drop)
        results[:] = [r for r in results if id(r) != _d]
    if dropped:
        bits = ", ".join(f"{b} (kept {k})" for b, _d, k, _n in dropped)
        notes.append(f"Calfrac prints each zone twice; kept one sheet per "
                     f"zone — Surface when it carries all four channels, "
                     f"Bottom Hole otherwise: {bits}")
    return results


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
                                           frames=frames))
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
                    results.append(_series(
                        meta, samples, data, "Trican treatment chart (raster)",
                        pno + 1, units, geom=info.get("geom"), frames=frames))
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
                for _n in (info.get("notes") or ()):
                    _trican_drops.setdefault(str(_n), []).append(pno + 1)
                data = {c["label"]: c["values"] for c in chans}
                units = {c["label"]: c["unit"] for c in chans}
                frames = {c["label"]: c["axis_frame"] for c in chans
                          if c.get("axis_frame")}
                if data:
                    stage = md.get("stage")
                    meta = {"title": f"Stage {stage or '?'}",
                            "uwi": md.get("uwi", ""), "stage": str(stage or ""),
                            "date": "", "start_time": "00:00:00",
                            "duration_min": len(samples) / 60.0,
                            "warnings": []}
                    results.append(_series(
                        meta, samples, data, "Trican treatment chart (raster)",
                        pno + 1, units, geom=info.get("geom"), frames=frames))
            except Exception as e:
                notes.append(f"p{pno + 1}: Trican chart failed — {e}")
            continue

        if raster and step1.detect(page):
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
                            frames=frames))
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

    _summary(bj_summary, "BJ chart" in chart_srcs,
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

    if not results:
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
    _normalise_tables(results, filename)
    return results, notes
