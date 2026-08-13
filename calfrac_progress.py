"""CalFrac/MView "Progress" charts — several zones plotted on ONE page.

Every other template in the corpus draws one stage per chart page. CalFrac's
older multi-zone reports don't: they file a "Progress <LSD> Surface" page whose
plot runs the length of the job and carries a caption naming the zones on it —

    Progress a-A082-I/094-G-01 Surface
    ...
     Zones 1-2
    MView - CWS-600 N2 Casing Clancy - 3/10/2015

The page never names a single stage, so frac_core.detect_meta leaves
meta.stage None and pipeline_export.build_well files the whole page under one
"?" block: two or five zones fused into a single graph, with no clock time
anywhere on it (the x axis is "Time (min)" counting from 0).

The clock times live on the *Multiple Zone Frac Treatment Summary* page that
precedes the charts, in a TIME INFO block whose columns line up with a
"ZONE #:" header row:

    ZONE #:        1       2
    Start Time:    19:37   23:38
    Stop Time:     22:00   1:30

so this module does two things: cut the page into one segment per zone, and
hand each segment its zone number and real start time.

Where the cuts go
-----------------
The printed times are not reliable enough to cut on. On 00023 page 1 they are
sane (zone 1 19:37-22:00, zone 2 23:38-1:30, matching the two bursts of pumping
in the data), but on page 6 of the same file every Stop Time repeats the next
zone's Start Time and the five zones span 35 hours of a 15-hour chart. Cutting
on those would shred good data.

The pumping itself is unambiguous: rate falls to zero between zones and stays
there for tens of minutes. So the cuts come from the DATA — the longest quiet
runs in slurry rate — and the caption says how many to make. The table is used
for naming and timestamps only, and only when it passes a sanity check.

If the data shows fewer quiet runs than the caption has zones, some zones ran
back to back and cannot be told apart. This emits the segments it can actually
see and records a warning naming the zones that stayed merged, rather than
inventing a boundary.
"""
import re

import numpy as np

from calfrac_summary import _rows

# Singular and plural both appear as real ranges — "Zones 12-14" and "Zones
# 15-18" sit in the same report as "Zone 1-12" — so the plural cannot be
# required. What has to be excluded is an ordinal: "Zone 8- 1st Attempt" reads
# as a range from 8 to 1. Single-zone captions ("Zone 8", "Zone 10") have no
# second number and never match, which is what keeps their pages unsplit.
ZONES_CAPTION = re.compile(r"\bZones?\s+(\d+)\s*-\s*(\d+)(?!\s*(?:st|nd|rd|th)\b)")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
# "ZONE #:" heads the older Multiple-Zone sheet; the 2018-vintage grid heads
# the same column with a bare "Zone".
_ZONE_HDR = re.compile(r"^ZONE\s*#|^Zone$", re.I)
# a zone column label: "7", "24", or a re-treat attempt "9A"
_ZONE_COL = re.compile(r"\d{1,2}[A-Za-z]?")
_TIME_ROW = re.compile(r"^\s*(Start|Stop|End)\s*Time", re.I)


# The chart kind is the last word(s) of an MView chart title, whatever the well
# is called: "Progress a-082-I/094-G-01 Surface", "Saguaro HZ Laprise
# 200/d-047-H/094-G-08/00 Bottom Hole". No \b before the name — these titles
# often run the well straight into the kind ("...094-G-01Bottom Hole") — and a
# trailing index is allowed ("... Surface 2").
_CHART_KIND = re.compile(r"(Surface|Bottom\s*Hole|Net\s*Pressure|Chemicals)"
                         r"\s*\d*\s*$", re.I)


def is_chart_page(page):
    """True when this MView page really is a chart.

    frac_core identifies a chart by its vector content, and a wellbore
    schematic passes that test: 00037's "Page 1/2" tubulars diagram was read
    as a chart, its depth column ("505.64") fitted as a time axis, and a
    506-minute WH Prop Conc series invented from the drawing. Worse, the page
    carries a "Zone 1", so the phantom landed in the same block as the real
    Zone 1 chart and — being first — its metadata and its flat fake curve won
    the merge.

    Across ten wells, 252 of 254 pages that extract data carry one of these
    chart titles; the two that do not are exactly those schematic pages.
    """
    try:
        text = page.get_text()
    except Exception:
        return True          # can't tell — don't drop it
    head = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return bool(_CHART_KIND.search(head))


def detect(page):
    """True for an MView chart page that may hold more than one zone.

    Do NOT key this on the title starting with "Progress". That word is part
    of some WELL names, not a marker of the layout: 00119's pages are titled
    "Saguaro HZ Laprise .../00 Surface" and carry perfectly good "Zones 5 -
    24" captions, and requiring "Progress" silently excluded every one of
    them — the whole file came back as a single "?" chart.

    Only the Surface page carries the caption; the Bottom Hole page beside it
    plots the same window with none at all. Both have to be recognised, so
    this accepts the whole chart family and lets the caller decide — a page
    with no caption and no captioned page directly before it is passed
    through untouched.
    """
    try:
        text = page.get_text()
    except Exception:
        return False
    if ZONES_CAPTION.search(text):
        return True
    head = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return bool(_CHART_KIND.search(head))


# A well is not fraced in 600 zones, and there is no zone 780. The widest real
# caption in the corpus is "Zones 5 - 24" and the highest number is 51.
MAX_ZONES = 60
MAX_ZONE_NO = 100


def zone_range(page):
    """-> (first, last) zone numbers named in the caption, or None.

    Bounded, and ascending only. Both guards exist because "Zone" is also a
    column header on the daily-report sheets, where the cell beneath it holds
    a phone number: "Zone / 403-999-6540" parsed as zones 403 to 999, and
    "780-779-3782" as a descending pair that a tidy-up swap turned into a
    plausible-looking two-zone range. Those pages are raster and never reach
    the splitter, but nothing about the regex itself stopped them.
    """
    text = page.get_text()
    for m in ZONES_CAPTION.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo < 1 or hi <= lo or hi - lo + 1 > MAX_ZONES or hi > MAX_ZONE_NO:
            continue
        # "780-814-4964" is ascending and only 35 apart, so the bounds alone
        # let it through; what gives it away is the third group.
        if text[m.end():m.end() + 1] == "-":
            continue
        return lo, hi
    return None


_FOOTER_DATE = re.compile(r"^MView\b.*?-\s*(\d{1,2})/(\d{1,2})/(20\d\d)\s*$", re.M)


def job_date(page):
    """-> 'YYYY-MM-DD' from the chart footer, or None.

    frac_core reads dates written as "Mar. 10, 2015"; these pages sign off with
    "MView - CWS-600 N2 Casing Clancy - 3/10/2015" instead, so without this
    every split zone exports against the 2000-01-01 placeholder.
    """
    try:
        m = _FOOTER_DATE.search(page.get_text())
    except Exception:
        return None
    if not m:
        return None
    mon, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mon <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{mon:02d}-{day:02d}"


_JOB_DATE_LABEL = re.compile(r"^Job\s*Date\b", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}
# "Mar 8, 2015", "Aug. 02 - 03, 2017", "Oct 21 - 22, 2016" -> the FIRST day
_WORD_DATE = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*(?:-\s*\d{1,2}\s*)?,?"
                        r"\s*(\d{4})")
# "8/23/2017 - 08/25/2017" -> the FIRST date
_SLASH_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d\d)")


def _job_date_value(text):
    m = _WORD_DATE.search(text)
    if m and m.group(1)[:3].lower() in _MONTHS:
        mon = _MONTHS[m.group(1)[:3].lower()]
        day, year = int(m.group(2)), int(m.group(3))
        if 1 <= day <= 31:
            return f"{year:04d}-{mon:02d}-{day:02d}"
    m = _SLASH_DATE.search(text)
    if m:
        mon, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mon <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{mon:02d}-{day:02d}"
    return None


def sheet_job_date(page, text=None):
    """The day the zones on a Multiple-Zone sheet were pumped, or None.

    THE CHARTS DO NOT SAY WHAT DAY THEY PLOT. Their only date is the MView
    footer, which is the date the chart was EXPORTED: 00194's three chart
    pages sign off 8/24, 8/25 and 8/25 for zones its own summary dates
    8/23-8/25, and 00017's eighteen zones all footer 3/9/2015 though the first
    eleven ran on the 8th.

    The summary sheet in front of them carries a GENERAL INFORMATION block
    with a "Job Date:" field, and that is the report saying when the job ran —
    "Mar 8, 2015", or a range, "8/23/2017 - 08/25/2017" / "Aug. 02 - 03,
    2017". A well reprints the sheet for each block of zones with that block's
    own date (00017: Mar 08 over zones 1-11, Mar 09 over zones 12-18; 00119:
    Apr 28 over zones 1-4, Apr 29 over the next twenty), so read per sheet,
    not per document.

    Where the field gives a range this returns its FIRST day — the day the
    block started. A block that runs past midnight is carried forward
    afterwards by its own clock.
    """
    try:
        if text is None:
            text = page.get_text()
        head = next((l.strip() for l in text.splitlines() if l.strip()), "")
        if not head.startswith("Multiple Zone Frac Treatment Summary"):
            # The 2018-and-later grid prints a Job Date per zone COLUMN, which
            # calfrac_summary.zone_clock already reads zone by zone. Reading a
            # row label here would hand every zone on the sheet the first
            # one's date.
            return None
        rows = _rows(page)
    except Exception:
        return None
    for _y, cells in rows:
        at = next((x for x, t in cells if _JOB_DATE_LABEL.match(t.strip())),
                  None)
        if at is None:
            continue
        for x, t in cells:
            if x <= at:
                continue
            got = _job_date_value(t)
            if got:
                return got
    return None


def job_date_before(dates, page_index):
    """The Job Date of the sheet a chart page sits behind, or None.

    The nearest sheet before it, not the merged run times_before() builds: a
    run can span a midnight and print two different days, and the last sheet
    of the run is the one whose zones this chart continues.
    """
    prior = [p for p in dates if p < page_index]
    return dates[max(prior)] if prior else None


_CALFRAC_MARK = re.compile(r"Calfrac\s+Service\s+Line", re.I)
_ANY_TIME_ROW = re.compile(r"(Start|Stop)\s*Time", re.I)


def _is_zone_grid(page):
    """The 2018-vintage Calfrac zone-major "Treatment Summary" grid.

    Same shape as the Multiple-Zone sheet — zones across the top, fields down
    the side, Start/Stop Time in hh:mm — but the page leads with the UWI line
    instead of a title. Every summary test in the app keys on that title, so
    this whole family of reports (00082, 00087 and their siblings) was read as
    having no summary page at all: nothing in the Tables tab, and no zone
    start times for the splitter, which is why 00082's "Zones 1-28" page came
    back as one fused 1300-minute graph.

    Recognised by the grid itself: a Calfrac page carrying a "Zone" header row
    with real zone columns under it, and a Start/Stop Time row. Zone labels
    are one or two digits, so the daily-report sheets — where "Zone" heads a
    cell holding a phone number — cannot supply a column here.
    """
    try:
        text = page.get_text()
    except Exception:
        return False
    if not (_CALFRAC_MARK.search(text) and _ANY_TIME_ROW.search(text)):
        return False
    try:
        rows = _rows(page)
    except Exception:
        return False
    for _y, cells in rows:
        if not any(_ZONE_HDR.match(t.strip()) for _x, t in cells):
            continue
        # one column is enough: a well's last summary sheet routinely holds
        # a single leftover zone (00099 puts zones 21-25 on one page and 26
        # alone on the next), and requiring two dropped that sheet, so the
        # last zone of the caption had no printed start and table_split
        # stopped one graph short.
        if any(_ZONE_COL.fullmatch(t.strip()) for _x, t in cells):
            return True
    return False


def _is_multizone(page):
    head = next((l.strip() for l in page.get_text().splitlines() if l.strip()), "")
    if head.startswith("Multiple Zone Frac Treatment Summary"):
        return True
    return _is_zone_grid(page)


def zone_times(page):
    """Multiple-Zone summary page -> {zone_no: {'start': 'HH:MM', 'stop': ...}}.

    Read positionally. The text stream is linear and the blank cells in these
    grids (a zone with no recorded stop, the "FRACED" markers on zones done in
    an earlier run) shift every later value onto the wrong zone if you walk it
    as a list.
    """
    try:
        rows = _rows(page)
    except Exception:
        return {}
    hdr = next(((y, cells) for y, cells in rows
                if any(_ZONE_HDR.match(t) for _x, t in cells)), None)
    if hdr is None:
        return {}
    hy, hcells = hdr
    # A re-treated zone is columned per attempt — "9A" and "9B" where every
    # other zone is a bare number — and requiring a bare number dropped both,
    # so the zone vanished from the table entirely. table_split walks the
    # caption's range until a zone has no printed start, so losing the last
    # zone that way made it stop one short: six files in the CalFrac corpus
    # split into exactly one fewer graph than their caption named.
    #
    # Both attempts map to the one zone the chart draws. Columns run left to
    # right in pumping order and the fills below use setdefault, so the first
    # attempt's times are the ones kept.
    cols = [(x, int(re.match(r"\d+", t.strip()).group(0)))
            for x, t in hcells if _ZONE_COL.fullmatch(t.strip())]
    if not cols:
        return {}
    # the gap between zone columns sets how far a value may sit from its own
    # header before it belongs to the neighbour
    pitch = (min(cols[i + 1][0] - cols[i][0] for i in range(len(cols) - 1))
             if len(cols) > 1 else 40.0)
    tol = max(12.0, pitch * 0.7)

    def owner(x):
        cx, zone = min(cols, key=lambda c: abs(c[0] - x))
        return zone if abs(cx - x) <= tol else None

    out = {}
    for y, cells in rows:
        if y <= hy:
            continue
        label = " ".join(t for _x, t in cells)
        m = _TIME_ROW.match(label)
        if not m:
            continue
        key = "start" if m.group(1).lower() == "start" else "stop"
        for x, t in cells:
            if not _HHMM.match(t.strip()):
                continue
            z = owner(x)
            if z is not None:
                out.setdefault(z, {}).setdefault(key, t.strip())
    return out


def sheets_for_document(doc):
    """-> ({page: zone times}, {page: 'Job Date:'}) for the summary sheets.

    Both come off the same pages, and a page's text costs a re-render of it,
    so they are read in ONE pass: scanning a 140-page book twice put 5 minutes
    on 00038.
    """
    times, dates = {}, {}
    for p in range(doc.page_count):
        page = doc[p]
        if not _is_multizone(page):
            continue
        t = zone_times(page)
        if t:
            times[p] = t
        d = sheet_job_date(page)
        if d:
            dates[p] = d
    return times, dates


def times_for_document(doc):
    """-> {page_index_of_summary: {zone: {...}}} for every multizone page."""
    return sheets_for_document(doc)[0]


def times_before(all_times, page_index):
    """The zone-time table governing a chart page.

    A well's report repeats the pattern <multizone summary><its charts>, so a
    chart belongs to the summary printed before it — but that summary can run
    over more than one page. 00017 puts zones 1-10 on one sheet and zone 11 on
    the next, and reading only the nearest sheet handed the twelve-zone chart a
    table with a single zone in it. Merge the whole contiguous run.
    """
    prior = sorted(p for p in all_times if p < page_index)
    if not prior:
        return dict(all_times[min(all_times)]) if all_times else {}
    run = [prior[-1]]
    for p in reversed(prior[:-1]):
        if p == run[-1] - 1:
            run.append(p)
        else:
            break
    merged = {}
    for p in sorted(run):
        for zone, info in all_times[p].items():
            merged.setdefault(zone, {}).update(info)
    return merged


def _quiet_runs(rate, sample_sec, frac):
    """[(start_idx, end_idx, length_s)] where pumping had stopped.

    The cut-off is relative to the rate the job actually ran at, not a fixed
    number: these charts carry N2 rate on the same axis as slurry rate and the
    working level differs by an order of magnitude between reports.
    """
    r = np.nan_to_num(np.asarray(rate, float), nan=0.0)
    live = r[r > 0.3]
    if live.size < 10:
        return []
    hi = float(np.percentile(live, 60))
    on = r > frac * hi
    runs, st = [], None
    for k, v in enumerate(on):
        if not v and st is None:
            st = k
        elif v and st is not None:
            runs.append((st, k))
            st = None
    if st is not None:
        runs.append((st, len(on)))
    # a quiet stretch at the very start or end is lead-in/tail, not a boundary
    runs = [(a, b) for a, b in runs if a > 0 and b < len(on)]
    return sorted(((a, b, (b - a) * sample_sec) for a, b in runs),
                  key=lambda t: t[2], reverse=True)


# how far below the working level counts as "stopped" — swept because a shut-in
# between zones reads as a hard zero on some reports and as a slow idle on
# others, and the caption tells us how many boundaries the right value finds
# Kept deliberately low. Raising the top of the ladder does not add coverage,
# it steals it: at 0.42 the slurry rate on 00017's "Zones 15-18" page happens
# to yield three gaps and would be taken in preference to the concentration
# curve, which gives the same three cleanly at every threshold.
_THRESHOLDS = (0.08, 0.10, 0.12, 0.18, 0.25, 0.35)

# Which curve marks the boundaries, in the order they are tried.
#
# Rate first: it is unambiguous when the pumps actually stopped between zones.
# But zones can run back to back with no rate drop at all — 00017's "Zones
# 12-14" and "Zones 15-18" show one rate gap for three and four zones — and
# there the proppant concentration still returns to zero at every changeover.
# Concentration is not tried first because it also drops to zero WITHIN a
# zone, during pad and flush: on 00023's two-zone page it finds four gaps
# where the rate finds the one real one.
_SIGNALS = ("Slurry Rate", "WH Prop Conc", "BH Prop Conc", "Tr Press")


def split_page(samples, data, nzones, sample_sec=1.0, min_gap_s=300.0):
    """Cut one Progress page into per-zone segments.

    -> [(start_idx, end_idx)] with exactly `nzones` entries, or None when the
    pumping data does not show that many treatments.

    The caption says how many zones are on the page, so the threshold that is
    right for this report is the one finding exactly that many boundaries. If
    none does, the page is left alone: a caption can be job-wide rather than
    per-page (00004 repeats "Zones 1-8" over single-treatment charts), and
    splitting on a count the data disagrees with would label real stages with
    zone numbers that are not theirs.
    """
    n = len(samples)
    if nzones <= 1 or n < 2:
        return None

    want = nzones - 1
    for name in _SIGNALS:
        signal = data.get(name)
        if signal is None:
            continue
        counts, runsets = [], []
        for frac in _THRESHOLDS:
            runs = [r for r in _quiet_runs(signal, sample_sec, frac)
                    if r[2] >= min_gap_s]
            counts.append(len(runs))
            runsets.append(runs)
        # Longest unbroken stretch of the ladder that agrees on the right
        # count. Hitting the number at a single threshold proves nothing: on
        # 00017's twelve-zone page the concentration dips eleven times briefly
        # enough to look like eleven boundaries at one setting, and those cuts
        # land mid-treatment. A real set of boundaries survives the sweep.
        start = length = 0
        i = 0
        while i < len(counts):
            if counts[i] != want:
                i += 1
                continue
            j = i
            while j + 1 < len(counts) and counts[j + 1] == want:
                j += 1
            if j - i + 1 > length:
                start, length = i, j - i + 1
            i = j + 1
        if length >= _MIN_STABLE:
            runs = runsets[start + length // 2]      # middle of the stable band
            return _bounds(sorted((a + b) // 2 for a, b, _len in runs), n)
    return None


# how many neighbouring thresholds must agree before a boundary set is believed
_MIN_STABLE = 3


def _bounds(cuts, n):
    out, prev = [], 0
    for c in cuts:
        out.append((prev, c))
        prev = c
    out.append((prev, n))
    return out


# How far a candidate gap may sit from the start time the summary prints for
# that zone and still be taken as that zone's boundary. The printed times are
# rounded to the minute and the gap midpoint is the middle of a shut-in that
# can run twenty minutes, so this is not tight.
_MATCH_TOL_MIN = 20.0
# A candidate set is only worth testing if it is in the right neighbourhood:
# a page of N zones that offers twice N gaps is not over-segmented, it is
# something else.
_MAX_EXTRA = 8


def split_page_by_table(samples, data, zones, ztimes, sample_sec=1.0,
                        min_gap_s=300.0):
    """Cut a page the data OVER-segments, letting the printed times choose.

    -> ([(start_idx, end_idx)], t0_minutes) or None.

    split_page believes a set of boundaries only when its COUNT is exactly the
    caption's, and that count is often one or two too many. Proppant
    concentration returns to zero during pad and flush as well as between
    zones, so 00194's "Zones 3-19" page shows nineteen quiet runs where
    seventeen zones need sixteen boundaries — stable at every threshold, and
    rejected. Its seventeen zones went out as one 23-hour graph while the
    "Zones 20-35" page beside it, whose concentration happens to dip exactly
    fifteen times, split cleanly. That is the whole of Carmine's report: one
    block of stages fused, the block after it fine.

    The Multiple-Zone summary prints when each zone started, and those times
    say which candidates are real. On that page they pick out sixteen of the
    nineteen to within 5 minutes and leave three — 669, 745 and 954 minutes —
    with no zone to belong to.

    The printed times are used only to CHOOSE among boundaries the pumping
    data proposed, never to place one: a zone the summary does not name still
    gets its boundary from the data, taken from the candidates left over
    between its neighbours.
    """
    n = len(samples)
    want = len(zones) - 1
    if want < 1 or n < 2:
        return None
    span_min = n * sample_sec / 60.0
    printed = {z: _minutes((ztimes.get(z) or {}).get("start")) for z in zones}
    printed = {z: m for z, m in printed.items() if m is not None}
    if len(printed) < max(2, int(round(0.5 * len(zones)))):
        return None                     # too little printed to choose with

    for name in _SIGNALS:
        signal = data.get(name)
        if signal is None:
            continue
        seen = set()
        for frac in _THRESHOLDS:
            runs = [r for r in _quiet_runs(signal, sample_sec, frac)
                    if r[2] >= min_gap_s]
            if not (want < len(runs) <= want + _MAX_EXTRA):
                continue                # exact counts are split_page's job
            cuts = tuple(sorted((a + b) // 2 for a, b, _l in runs))
            if cuts in seen:
                continue
            seen.add(cuts)
            got = _match_cuts([c * sample_sec / 60.0 for c in cuts],
                              zones, printed, span_min)
            if got is None:
                continue
            chosen, t0 = got
            idx = [int(round(c * 60.0 / sample_sec)) for c in chosen]
            if any(c <= 0 or c >= n for c in idx) or \
                    any(idx[i] >= idx[i + 1] for i in range(len(idx) - 1)):
                continue
            return _bounds(idx, n), t0
    return None


def _match_cuts(cands, zones, printed, span_min):
    """-> ([cut_minute per zone after the first], t0) or None."""
    # Where on the clock does the page open? Every (printed zone, candidate)
    # pair implies an origin; the right one is agreed by many pairs at once,
    # the same test anchor_t0 makes.
    implied = [(printed[z] - c) % DAY for z in printed for c in cands]
    implied += [printed[zones[0]] % DAY] if zones[0] in printed else []
    if not implied:
        return None
    # Densest window of width 2*tol, over the sorted values wrapped once round
    # the clock. A 30-zone page implies 900 origins and the pairwise form of
    # this cost minutes per page.
    order = sorted(implied)
    ring = order + [v + DAY for v in order]
    best, best_n, j = None, 0, 0
    for i in range(len(order)):
        if j < i:
            j = i
        while j + 1 < len(ring) and ring[j + 1] - ring[i] <= 2 * _MATCH_TOL_MIN:
            j += 1
        if j - i + 1 > best_n:
            best_n = j - i + 1
            best = (sum(ring[i:j + 1]) / best_n) % DAY
    if best is None or best_n < max(2, int(round(0.5 * len(printed)))):
        return None

    # The window's centre is only an estimate — good to about a quarter hour,
    # because a zone's printed start is not the instant the pumps came back
    # on. Match against it, re-read the origin off the zones that matched, and
    # match again: taking the nearest candidate zone by zone against a t0 a
    # sixth of an hour out walked 00275 onto its neighbour's boundary at zone
    # 18 and lost the page.
    pick = want = None
    for _pass in range(3):
        want = _targets(zones, printed, best, span_min)
        if want is None:
            return None
        pick = _assign(cands, want)
        if pick is None:
            return None
        off = sorted(cands[pick[k]] - want[k]
                     for k in range(len(want)) if want[k] is not None)
        if not off:
            return None
        mid = off[len(off) // 2]
        if abs(mid) < 0.5:
            break
        best = (best + mid) % DAY       # slide the origin onto the data
    if max(abs(cands[pick[k]] - want[k])
           for k in range(len(want)) if want[k] is not None) > _MATCH_TOL_MIN:
        return None

    # a zone the summary skipped takes a leftover candidate from between its
    # named neighbours, placed where an even run of treatments would put it
    taken = set(pick)
    out, i = [], 0
    while i < len(want):
        if want[i] is not None:
            out.append(cands[pick[i]])
            i += 1
            continue
        j = i
        while j < len(want) and want[j] is None:
            j += 1
        lo_c = out[-1] if out else 0.0
        hi_c = cands[pick[j]] if j < len(want) else span_min
        pool = sorted(c for k, c in enumerate(cands)
                      if lo_c < c < hi_c
                      and (k not in taken or i <= _slot_of(pick, k) < j))
        m = j - i
        if len(pool) < m:
            return None
        out.extend(_even(pool, lo_c, hi_c, m))
        i = j
    if len(out) != len(zones) - 1 or any(out[k] >= out[k + 1]
                                        for k in range(len(out) - 1)):
        return None
    return out, best


def _slot_of(pick, k):
    try:
        return pick.index(k)
    except ValueError:
        return -1


def _targets(zones, printed, t0, span_min):
    """Each zone after the first as minutes from the page's own start.

    None where the summary prints no start for that zone. A clock time only
    says where in a DAY the zone began, so on a page longer than a day it
    names two positions; zones run in order, so take the first one past the
    zone before it.
    """
    out, after = [], 0.0
    for z in zones[1:]:
        if z not in printed:
            out.append(None)
            continue
        e = (printed[z] - t0) % DAY
        while e <= after - _MATCH_TOL_MIN:
            e += DAY
        if e > span_min + _MATCH_TOL_MIN:
            return None                 # printed past the end of this page
        out.append(e)
        after = e
    return out


def _assign(cands, want):
    """One candidate per zone, in order, closest to the printed times overall.

    -> [candidate INDEX per zone] or None. Matching zone by zone to the
    nearest candidate is what breaks when the fitted origin is a few minutes
    out: one zone takes its neighbour's boundary and every zone after it is
    lost. Choosing the whole set at once cannot do that — a subsequence that
    steals a boundary pays for it at the next zone.

    A zone with no printed start costs nothing and simply consumes one
    candidate, which is what reserves a boundary for it inside the run its
    neighbours bracket.
    """
    nz, nc = len(want), len(cands)
    if nz > nc:
        return None
    inf = float("inf")
    dp = [[inf] * nc for _ in range(nz)]
    back = [[-1] * nc for _ in range(nz)]
    for i in range(nc):
        dp[0][i] = 0.0 if want[0] is None else abs(cands[i] - want[0])
    for k in range(1, nz):
        run_best, run_arg = inf, -1
        for i in range(1, nc):
            if dp[k - 1][i - 1] < run_best:
                run_best, run_arg = dp[k - 1][i - 1], i - 1
            if run_best == inf:
                continue
            cost = 0.0 if want[k] is None else abs(cands[i] - want[k])
            dp[k][i], back[k][i] = run_best + cost, run_arg
    end = min(range(nc), key=lambda i: dp[nz - 1][i])
    if dp[nz - 1][end] == inf:
        return None
    out, i = [0] * nz, end
    for k in range(nz - 1, -1, -1):
        out[k] = i
        i = back[k][i]
        if i < 0 and k:
            return None
    return out


def _even(cands, lo, hi, m):
    """The m of `cands`, in order, sitting closest to an even split of (lo,hi).

    Which leftover gap is zone 11's boundary and which is a dip inside zone
    10? Nothing printed says, so the tie-break is that treatments on one page
    take comparable times: on 00194 the choice is between 590 and 669 minutes
    for the one zone between boundaries at 500 and 685, and 590 splits that
    stretch nearly in half while 669 leaves a 16-minute treatment.
    """
    if len(cands) == m:
        return list(cands)
    want = [lo + (hi - lo) * (k + 1) / (m + 1) for k in range(m)]
    inf = float("inf")
    # dp[k][i]: least error placing targets 0..k-1 in candidates 0..i-1
    dp = [[inf] * (len(cands) + 1) for _ in range(m + 1)]
    back = [[None] * (len(cands) + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for i in range(len(cands) + 1):
        dp[0][i] = 0.0
    for k in range(1, m + 1):
        for i in range(k, len(cands) + 1):
            skip = dp[k][i - 1]
            take = dp[k - 1][i - 1] + abs(cands[i - 1] - want[k - 1])
            if take <= skip:
                dp[k][i], back[k][i] = take, True
            else:
                dp[k][i], back[k][i] = skip, False
    out, k, i = [], m, len(cands)
    while k > 0:
        if back[k][i]:
            out.append(cands[i - 1])
            k -= 1
        i -= 1
    return list(reversed(out))


def table_split(ztimes, lo, hi, n, sample_sec, span_min):
    """Cut at the times the summary table prints, when the data cannot.

    Zones can run back to back with no break at all — 00017's twelve-zone
    overview pumps almost continuously for 1250 minutes — and then the chart
    holds no boundary to find. The table still records when each zone started,
    and on that page those times are coherent: eleven zones from 3:20 to 23:36,
    1216 minutes across a 1250-minute plot.

    -> ([(start_idx, end_idx)], [zone_no]) or None. The zone list comes from
    the table rather than the caption, which tends to name a wider range than
    the chart actually holds.
    """
    zones, z = [], lo
    while z <= hi and _minutes((ztimes.get(z) or {}).get("start")) is not None:
        zones.append(z)
        z += 1
    if len(zones) < 2:
        return None
    offs, prev, acc = [0.0], _minutes(ztimes[zones[0]]["start"]), 0.0
    for zz in zones[1:]:
        m = _minutes(ztimes[zz]["start"])
        step = (m - prev) % DAY            # a step of 0 means a repeated cell
        if step <= 0:
            return None
        acc += step
        offs.append(acc)
        prev = m
    # The zones must lie along THIS chart: overrunning it means the table
    # describes a different window, and bunching into the first half means the
    # times are chained placeholders rather than real starts.
    if not (span_min * 0.5 <= acc <= span_min * 1.02):
        return None
    cuts = [int(o * 60.0 / sample_sec) for o in offs[1:]]
    if any(c <= 0 or c >= n for c in cuts):
        return None
    return _bounds(cuts, n), zones


def _minutes(hhmm):
    m = _HHMM.match(hhmm or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


DAY = 24 * 60


def zone_start_minutes(times, zone):
    """A zone's printed Start Time as minutes since midnight, or None."""
    return _minutes((times.get(zone) or {}).get("start"))


def anchor_t0(zone_nos, offsets_min, times, tol_min=25.0):
    """Where on the clock the chart starts, from the zones' printed times.

    Rather than stamping each zone with its own table entry, this fits ONE
    origin for the page and reads every zone off the chart's own axis from
    there. The axis is exact and evenly spaced; the printed times are rounded
    to the minute, are missing for some zones, and on some sheets are plain
    wrong. Anchoring uses them for the one thing they are reliable for —
    saying where on the clock the picture sits — and takes the spacing from
    the chart.

    Each zone with a printed start implies an origin of (start - its offset).
    Agreement between those implied origins is the check: zones really pumped
    in the order and spacing the chart shows, so a table that describes this
    chart produces a cluster, and one that does not scatters.

    -> (t0_minutes_since_midnight, n_supporting) or None.
    """
    implied = []
    for zone, off in zip(zone_nos, offsets_min):
        m = _minutes((times.get(zone) or {}).get("start"))
        if m is not None:
            implied.append((m - off) % DAY)
    if len(implied) < 2:
        return None

    def near(a, b):
        d = abs(a - b) % DAY
        return min(d, DAY - d) <= tol_min

    best, best_n = None, 0
    for cand in implied:
        grp = [v for v in implied if near(v, cand)]
        if len(grp) > best_n:
            # average within the cluster, unwrapped around the candidate so a
            # group straddling midnight does not average to the far side
            off = [((v - cand + DAY / 2) % DAY) - DAY / 2 for v in grp]
            best, best_n = (cand + sum(off) / len(off)) % DAY, len(grp)
    # a lone agreeing pair proves nothing; require a real majority
    if best_n < 2 or best_n * 2 < len(implied):
        return None
    return best, best_n
