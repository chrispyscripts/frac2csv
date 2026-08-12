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
import sanjel
import step_vec
import pipeline_export as pe
import sk_fracr as sk
import slb
import trican2

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
                    _last_progress, zclocks=None):
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
        if by_table:
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
    page_date = getattr(meta, "date", "") or cprog.job_date(page) or ""
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
    # the last captioned Progress page, so its uncaptioned twin can borrow its
    # zones AND its cut positions
    _last_progress = [None]
    # the Treatment Summary grid's per-zone start time and Job Date, read once
    # per document and only when a CalFrac chart actually needs it
    _zone_clocks = [None]
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
            # The interval identifier can carry a letter — a re-frac is filed
            # as "Interval 4A". Matching bare digits here did not merge those
            # charts, it DROPPED them: 00001 prints intervals 1, 2, 3, 4A, 4B,
            # 5A, 5B, 6A, 6B and 7, and only 1, 2, 3 and 7 came out — six of
            # its ten intervals produced nothing at all, silently, through the
            # same no-note skip the comment above describes.
            titled = re.search(
                r"Interval\s+\d{1,3}[A-Za-z]?\s*[-–]\s*(?:Entire|Main)\s+"
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
            continue

        if slb.detect(page):
            try:
                for meta, samples, data, units in \
                        slb.extract_page_blocks(page, sample_sec):
                    results.append(_series(_md(meta), samples, data,
                                           "SLB PRC chart", pno + 1, units))
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
                meta = {"title": f"Treatment interval {md.get('stage') or '?'}",
                        "uwi": md.get("uwi", ""), "stage": str(md.get("stage") or ""),
                        "date": "", "start_time": "00:00:00",
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
                        meta = {"title": f"Interval {md.get('stage') or '?'} "
                                f"({kind})", "uwi": md.get("uwi") or "",
                                "stage": str(md.get("stage") or ""),
                                "date": md.get("date") or "",
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
            if data and cprog.detect(page):
                # a "Progress" page: several zones on one plot, no stage named
                if _zone_times[0] is None:
                    _zone_times[0] = cprog.times_for_document(doc)
                if _zone_clocks[0] is None:
                    _zone_clocks[0] = calfrac_summary.zone_clock(doc)
                for part in _split_progress(page, meta, samples, data,
                                            cprog.times_before(_zone_times[0], pno),
                                            sample_sec, notes, pno, _last_progress,
                                            _zone_clocks[0]):
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
    if any(r.get("source") == "MView chart" for r in results):
        if _zone_clocks[0] is None:
            _zone_clocks[0] = calfrac_summary.zone_clock(doc)
        clocks = _zone_clocks[0]
        if clocks:
            restamped, blanked = 0, []
            for r in results:
                md = r.get("meta", {})
                if r.get("source") != "MView chart" or \
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

    if not results:
        extra = "" if raster else \
            " (raster/scanned templates need the tesseract OCR engine)"
        notes.append(f"No extractable charts or tables found in {npages} pages{extra}.")
    _normalise_tables(results, filename)
    return results, notes
