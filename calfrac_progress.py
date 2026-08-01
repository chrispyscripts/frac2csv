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
_ZONE_HDR = re.compile(r"^ZONE\s*#", re.I)
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


def _is_multizone(page):
    head = next((l.strip() for l in page.get_text().splitlines() if l.strip()), "")
    return head.startswith("Multiple Zone Frac Treatment Summary")


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
    cols = [(x, int(t)) for x, t in hcells if re.fullmatch(r"\d{1,2}", t.strip())]
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


def times_for_document(doc):
    """-> {page_index_of_summary: {zone: {...}}} for every multizone page."""
    out = {}
    for p in range(doc.page_count):
        page = doc[p]
        if _is_multizone(page):
            t = zone_times(page)
            if t:
                out[p] = t
    return out


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
